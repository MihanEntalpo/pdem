#!/usr/bin/python3
# -*- coding: utf-8 -*-
'''
pdem-server на питоне
'''

__author__ = "Mihanentalpo"
__version__ = "0.1.4"


import logging

from tornado.ioloop import IOLoop
from tornado.iostream import IOStream
from tornado.tcpserver import TCPServer
from tornado.tcpclient import TCPClient

import collections
import subprocess
import os
import sys
import time
import signal


class Tools(object):
    """
    Статический класс с разными инструментами
    """
    @staticmethod
    def explode_by_spaces(x):
        """
        Разбивает массив байтов по пробелам,
        игнорируя те пробелы, перед которыми стоит слэш,
        но только если это не двойной слеш
        """
        assert isinstance(x, bytearray) or isinstance(x, bytes)
        parts = []
        cur_part = bytearray()
        prev_slash = False
        slash_byte = b"\\"[0]
        state = 0
        l = len(x)
        for i in range(l):
            if x[i] == slash_byte:
                if prev_slash:
                    cur_part.append(slash_byte)
                    prev_slash = False
                else:
                    prev_slash = True
            elif x[i] == 32:
                if prev_slash:
                    cur_part.append(32)
                    prev_slash = False
                elif len(cur_part) > 0:
                    parts.append(bytes(cur_part))
                    cur_part = bytearray()
            else:
                if prev_slash:
                    cur_part.append([slash_byte, x[i]])
                else:
                    cur_part.append(x[i])

        if len(cur_part):
            parts.append(bytes(cur_part))

        return parts

    @staticmethod
    def addSlashes(s):
        "Добавляет слэши перед пробелами и слешами в байтовом массиве"
        assert isinstance(s, bytearray) or isinstance(s, bytes)
        l = len(s)
        r = bytearray()
        slash = ord(b"\\")
        for i in range(l):
            if s[i] == 32 or s[i] == slash:
                r.append(slash)
            r.append(s[i])
        return r

    @staticmethod
    def parseInt(x):
        "Преобразовать что угодно в целое число. Если не получится - вернуть 0"
        try:
            v = int(x)
        except ValueError:
            v = 0
        return v

    @staticmethod
    def list_item(l, index, default=None):
        "Получить элемент массива, если такого элемента нет - вернёт default"
        try:
            v = l[index]
        except IndexError:
            v = default
        return v

    @staticmethod
    def stripLines(text):
        "Очистить строки текста от начальных пробелов"
        return "\n".join(
            [l.strip(" \t")
             for l in text.strip("\n\t ").split("\n")])


class PdemServer(TCPServer):
    """
    Класс-сервер отвечающий за работу сетевой подсистемы Pdem
    """

    def __init__(self, io_loop=None, ssl_options=None, **kwargs):
        """Конструктор"""
        self.port = 5555
        self.addr = "localhost"
        self.manager = ConnectionManager(self)
        self.processes = ProcessManager(self)
        self.logger = logging.getLogger("pdem.PdemServer")
        self.timeout_descriptor = 0
        self.app = None
        self.running_state = False

        logging.info('pdem server started')
        TCPServer.__init__(self, io_loop=io_loop, ssl_options=ssl_options,
                           **kwargs)

    def setApp(self, app):
        self.app = app

    def setPort(self, port):
        self.port = port

    def setAddr(self, addr):
        self.addr = addr

    def run(self):
        try:
            self.listen(self.port, self.addr)
            self._start_timer()
            self.running_state = True
        except Exception as e:
            self.logger.error(str(e))
            raise e

    def _start_timer(self):
        self._set_timeout()

    def _set_timeout(self):
        "Установить вызов хэндлера через 1 секунду"
        if self.timeout_descriptor == 0:
            self.timeout_descriptor = IOLoop.instance().call_later(
                1, self._handle_timeout
            )

    def _handle_timeout(self):
        "Обработчик таймаута, вызывается постоянно раз в секунду"
        self.timeout_descriptor = 0
        self._set_timeout()
        self.processes.increment_times()

    def handle_stream(self, stream, address):
        """Обработчик подключения, передаём его в менеджер подключений"""
        self.logger.info("Accepting connection from {}".format(address))
        self.manager.connect(stream, address)

    def stop(self):
        "Выключить сервер"
        self.logger.debug("Stop listening")
        TCPServer.stop(self)

    def die(self):
        """Завершить работу сервера, всё поубивать, приготовиться к смерти"""
        self.stop()
        self.logger.debug("Unlink process and connection managers")
        self.manager.server = None
        self.processes.server = None
        if self.timeout_descriptor != 0:  # Если таймаут еще не отработал убъем
            IOLoop.instance().remove_timeout(self.timeout_descriptor)


class ConnectionManager(object):
    """
    Класс менеджера подключений, хранит все подключения и позволяет
    управлять ими.
    """
    def __init__(self, server):
        self.connections = {}
        self.server = server
        self.logger = logging.getLogger("pdem.ConnectionManager")

    def connect(self, stream, address):
        """
        Обработчик подключения - создаёт класс подключения и заносит его в хэш

        Эту функцию вызывает TcpServer или его наследник
        """
        connection = PdemConnection(stream, address, self)
        self.connections[address] = connection
        self.logger.debug("Connection created and added")
        self.logger.debug("Connections count:{}".format(len(self.connections)))

    def disconnect(self, address):
        """
        Функция вызывается PdemConnection при обрыве соединения
        """
        self.logger.info("Disconnection occured from {}".format(address))
        del self.connections[address]
        self.logger.debug("Connections count:{}".format(len(self.connections)))

    def close_all(self):
        """Закрыть все открытые соединения"""
        for conn in self.connections:
            self.connections[conn].close()


class PdemConnection(object):
    """Класс сетевого подключения"""
    def __init__(self, stream, address, manager):
        self.manager = manager
        self.stream = stream
        self.address = address
        self.stream.set_close_callback(self._on_close)
        self.logger = logging.getLogger("pdem.PdemConnection")
        self.logger.debug("PdemConnection created")
        self.stream.read_until_close(self._data_receive_done,
                                     self._data_receive)
        self.buffer = bytearray()
        # Кодировка клиента, когда-нибудь она будет выбираться, пока прописана жёстко
        self.client_enc = "UTF-8"

    def toBytes(self, s):
        """Преобазовать в байты строку в кодировке клиента"""
        return s.encode(self.client_enc)

    def toStr(self, bt):
        """Преобразовать в строку последовательность байт в кодировке клиента"""
        return bt.decode(self.client_enc)

    def writePackage(self, data):
        "Записать в сокет данные в виде пакета [ANS[данные]ANS]"
        assert isinstance(data, bytearray) or isinstance(data, bytes)
        self.write(b"[ANS[" + data + b"]ANS]")

    def write(self, data):
        "Записать данные в сокет данного подключения"
        assert isinstance(data, bytearray) or isinstance(data, bytes)
        try:
            self.logger.debug("Writing data:" + data.decode("UTF-8"))
            self.stream.write(data)
        except Exception as e:
            self.logger.error("Error while writing data:{}".format(e))

    def close(self):
        "Закрыть подключение"
        self.logger.info("Closing connection by close() method")
        self.stream.close()

    def _on_close(self):
        """Обработчик закрытия сокета"""
        self.logger.info('Connection is closed by %s', self.address)
        self.manager.disconnect(self.address)

    def _data_receive(self, data):
        """Приём кусочка данных"""
        try:
            text = self.toStr(data)
        except Exception:
            text = "Exception on decode of data."
        self.logger.debug("Data arrived:" + text)
        self.buffer += data
        # Пока вырезаются куски - будем вырезать!
        while self._try_to_cut_package():
            pass

    def _data_receive_done(self, data):
        """Функция-заглушка"""
        pass

    def _try_to_cut_package(self):
        """Попытка вырезать пакет из буфера данных"""

        start = b"[CMD["
        end = b"]CMD]"
        start_pos = self.buffer.find(start)
        if (start_pos > -1):
            if (start_pos > 0):
                self.buffer = self.buffer[start_pos::]
            end_pos = self.buffer.find(end)
            if (end_pos > -1):
                package = self.buffer[len(start):end_pos:]
                self.buffer = self.buffer[end_pos + len(end)::]
                self._parse_package(package)
                return True
        return False

    def _parse_package(self, package):
        "Распарсить пакет и отправить его на обработку"
        if (self.manager.server is None
                or
                self.manager.server.running_state is False):
            self.logger.debug("Server not in running state,cancelling package")

            return
        self.logger.debug("Package:" + package.decode("UTF-8"))
        parts = Tools.explode_by_spaces(package)
        if (len(parts) == 0):
            self.logger.debug("Package parsed to zero parts")
        else:
            self.logger.debug("Starting Executor with {} and {}".format(
                parts[0], parts[1::]))
            CommandExecutor.doCommand(self, parts[0], parts[1::])


class ProcessManager(object):
    """
    Класс, отвечающий за управление набором процессов
    """
    def __init__(self, server):
        self.logger = logging.getLogger("pdem.ProcessManage")
        self.processes = {}
        self.server = server
        self.default_enc = "UTF-8"

    def increment_times(self):
        """
        Увеличить время работы всех процессов на 1, и расчитать время
        когда окончится их работа (если progressEnabled)
        """
        for name in self.processes:
            proc = self.processes[name]
            if proc.alive:
                proc.life_time += 1
                if proc.progressEnabled:
                    p = proc.progress
                    if (p > 0):
                        proc.est_time = int(proc.life_time / p * (100 - p))
                    else:
                        proc.est_time = -1
                else:
                    proc.est_time = -1

    def start_process(self, name, title, ptype, command):
        """Запустить новый процесс"""
        assert isinstance(name, str)
        assert isinstance(title, str)
        assert isinstance(ptype, str)
        assert isinstance(command, str)
        if ptype != 'local':
            raise Exception("Process type must be 'local'")
        if name in self.processes and self.processes[name].alive:
            self.logger.info("Process with name '{"+name+"}' already running")
            raise Exception(
                "Process with name '{}' already running".format(name)
            )
        self.processes[name] = ProcessHandler(name, title, ptype, command)

    def kill(self, name):
        "Убить процесс с именем name"
        if name in self.processes:
            assert isinstance(name, str)
            proc = self.processes[name]
            if proc.alive:
                proc.processObj.kill()
        else:
            raise Exception("Process doesn't exists")

    def burn_dead(self):
        "Сжечь мёртвых (удалить отработавшие процессы)"
        remove = list()
        for proc in self.processes:
            if not self.processes[proc].alive:
                remove.append(proc)
        for remItem in remove:
            del self.processes[remItem]

    def get_proc_by_name(self, name):
        """
        Get process by it's name
        :param name: str
        :return: ProcessHandler
        """
        if name in self.processes:
            return self.processes[name]
        else:
            return None

    def get_proc_list(self, showdead=True):
        """
        Generate list of processes, prepared to send it to client
        :return str bytearray, ready to send
        """
        result_lines = []

        result_data = b""
        for name in self.processes:
            proc = self.processes[name]
            if proc.alive or showdead:
                progr_enb = ("supportsprogress="
                             + "1" if proc.progressEnabled else "0")
                progr = "progress=" + str(proc.progress)
                timeest = "timeestimated=" + str(proc.est_time)
                line = [name, proc.title, proc.ptype, proc.command,
                        str(proc.life_time), progr_enb, progr, timeest]

                for vname in proc.variables:
                    line.append(vname + "=" + proc.variables[vname])

                if proc.alive:
                    line.append("alive")
                else:
                    line.append("dead")

                encoded_line = [Tools.addSlashes(
                    item.encode("UTF-8")
                ) for item in line]

                result_lines.append(b" ".join(encoded_line) + b"\n")
        if (len(result_lines)):
            result_data = b"".join(result_lines)
        else:
            result_data = b"0"

        return result_data


class ProcessHandler(object):
    """
    Класс, хранящий данные о запущеном процессе,

    И обеспечивающий обработку получаемых от него данных
    """
    def __init__(self, name, title, ptype, command):
        self.name = name
        self.title = title
        self.command = command
        self.buffer = bytearray()
        self.progressEnabled = False
        self.progress = 0
        self.alive = True
        self.variables = {}
        self.ptype = ptype
        self.est_time = 0
        self.life_time = 0
        self.process_enc = "UTF-8"

        self.logger = logging.getLogger("pdem.ProcessHandler")
        self.logger.info(
            "Created handler for {}, named {}".format(command, name)
        )
        self.processObj = None
        self._run_command(command)

    def toStr(self, bt):
        "Преобразовать байты в строку в кодировке процесса"
        return bt.decode(self.process_enc)

    def toBytes(self, s):
        "Преобразовать строку в байты в кодировке процесса"
        return s.encode(self.process_enc)

    def _run_command(self, command):
        """
        Функция запуска команды в отдельном процессе
        """
        ioloop = IOLoop.instance()
        PIPE = subprocess.PIPE

        self.processObj = subprocess.Popen(
            command, shell=True,
            stdin=PIPE, stdout=PIPE,
            stderr=subprocess.STDOUT, close_fds=True
        )

        fd = self.processObj.stdout.fileno()

        def recv(*args):
            data = self.processObj.stdout.readline()
            if data:
                self._command_data_arrived(data)
            elif self.processObj.poll() is not None:
                ioloop.remove_handler(fd)
                self._command_callback(None)

        ioloop.add_handler(fd, recv, ioloop.READ)

    def _command_callback(self, data):
        """
        Обработчик данных, пришедших от процесса (либо данные либо окончание)
        """
        if data is not None:
            self._command_data_arrived(data)
        else:
            self._command_finished()

    def _command_data_arrived(self, data):
        """
        Обработчик ситуации, когда пришли данные
        """
        text = self.toStr(data)
        self.logger.debug("Data from process arrived:" + text)

        self.buffer += data
        while self._try_to_cut_package():
            pass

    def _command_finished(self):
        """
        Обработчик ситуации когда команда завершена
        """
        self.logger.info("Process is done")
        self.alive = False
        self.buffer = bytearray()

    def _parse_package(self, package):
        self.logger.debug(
            "proc:{} Process sended package to us:{}".format(
                self.name,
                package.decode("UTF-8")
            )
        )

        if (package == b"progressenabled"):
            self.progressEnabled = True
            self.logger.info(
                "proc:{} ProgressEnabled set to True".format(self.name)
                )

        elif (package[0:9:] == b"progress="):
            self.progress = Tools.parseInt(package[9::])
            self.progressEnabled = True
            self.logger.info("proc:{} Progress set to {}".format(
                self.name,
                self.progress
                )
            )

        elif (package[0:4] == b"var:"):
            eq_pos = package.find(b"=")
            if (eq_pos > 3):
                varName = self.toStr(bytes(package[4:eq_pos:]))
                val = self.toStr(bytes(package[eq_pos+1::]))
                self.variables[varName] = val
                self.logger.info("proc:{} Var '{}' set to '{}'".format(
                    self.name,
                    varName,
                    val
                ))

    def _try_to_cut_package(self):
        """
        Попытка вырезать пакет из буфера данных
        """
        start = b"[PDEM["
        end = b"]PDEM]"
        start_pos = self.buffer.find(start)
        if start_pos > -1:
            if start_pos > 0:
                self.buffer = self.buffer[start_pos::]
            end_pos = self.buffer.find(end)
            if end_pos > -1:
                package = self.buffer[len(start):end_pos:]
                self.buffer = self.buffer[end_pos + len(end)::]
                self._parse_package(package)
                return True
        return False


class CommandExecutor(object):
    """
    Класс, занимающийся исполнением команд клиента

    Полностью статический.
    Все функции, начинающиеся с do_ являются исполнителями команд
    """

    logger = False
    help_text = None

    @staticmethod
    def doCommand(connection, cmd, parameters):
        ce = CommandExecutor
        CommandExecutor.logger = logging.getLogger("pdem.CommandExecutor")

        methods = [m for m in dir(ce) if (hasattr(
            getattr(ce, m), "__call__")
        ) and m.startswith("do_")]

        command = "do_" + connection.toStr(cmd)
        if (command in methods):
            try:
                func = getattr(CommandExecutor, command)
                CommandExecutor.logger.info("Running command:" + command)
                func(connection, parameters)
            except Exception as e:
                exctxt = str(e)

                connection.writePackage(b"ERROR:" + connection.toBytes(exctxt))
                CommandExecutor.logger.error(str(e))
        else:
            connection.writePackage(b"ERROR:unknown command")

    @staticmethod
    def do_help(connection, parameters):
        """
        Show this HELP
        no parameters required
        """
        if CommandExecutor.help_text is not None:
            data = CommandExecutor.help_text
        else:

            try:
                ce = CommandExecutor

                methods = [m for m in dir(ce) if isinstance(
                    getattr(ce, m), collections.Callable
                ) and m.startswith("do_")]

                data = """
                pdem protocol help:\n

                Every package has a format:
                "[CMD[data]CMD]"

                `data` consists of:
                command - one `word`, means "what to do"
                parameters - sequence of `words`, which are need to run command

                `word` - is a sequence of any bytes exсept " " (space character)
                to insert a space character to a word, it must be escaped with
                backslash, like this: hello\ world - it's a `word` with space
                inside.
                The backslash itself doesnt mean anythong special, it become escape
                character only when placed before space character. To place
                backslash in a normal way, you have to double it, for example:
                hello\\ world - this is two `words`, on is the "hello\" and other
                is "world".

                Commands and their descriptions:

                """

                for m in methods:

                    data += "".join(["Command `",
                                     m.replace("do_", ""),
                                     "`, information:\n"])

                    data += getattr(ce, m).__doc__ + "\n\n"

                CommandExecutor.help_text = data
            except Exception as e:
                raise Exception(str(e) + " at line " +
                                str(sys.exc_info()[-1].tb_lineno))

        connection.writePackage(connection.toBytes(Tools.stripLines(data)))

    @staticmethod
    def do_quit(connection, parameters):
        """
        Turn pdem-server off
        no parameters required
        """
        connection.manager.server.app.die()

    @staticmethod
    def do_disconnect(connection, parameters):
        """
        Disconnect current client
        no parameters required
        """
        connection.close()

    @staticmethod
    def do_show(connection, parameters):
        """
        Show how command would be parsed and interpreted.
        Usefull to understand, how doest pdem parses backslashes and spaces
        in some compicated cases. Try to prepend any command with "show",
        like this: "[CMD[show kill processname]CMD]"
        parameters: any number more or equal than 1
        """
        if len(parameters) == 0:
            raise Exception("Must be at least one parameter")
        else:
            result = b"Parse result:\n"
            result += b"Command:`" + parameters[0] + b"`\n"
            for i in range(1, len(parameters)):
                result += (b"Parameter #" + bytes([i+ord("0")]) + b":`"
                           + parameters[i] + b"`\n")
            connection.writePackage(result)

    @staticmethod
    def do_disconnectall(connection, parameters):
        """Disconnect all clients
        no parameters required"""
        connection.manager.close_all()

    @staticmethod
    def do_kill(connection, parameters):
        "убить 1 или несколько процессов"
        if len(parameters) > 0:
            processes = connection.manager.server.processes
            for param in parameters:
                CommandExecutor.logger.info("Killing process "
                                            + connection.toStr(param))
                processes.kill(connection.toStr(param))
        else:
            raise Exception("Should be at least 1 parameter")

    @staticmethod
    def do_runprocess(connection, parameters):
        """
        Start process
        parameters: name title processtype command
        name: unique name of process, used to identify it from others
        title: human readable title of process, just for convenience
        processtype: type of process, now only "local" is supported
        command: command, that runs a process, for "local" processtype it's
        a shell command, that would be executed by pdem
        """
        if len(parameters) != 4:
            l = len(parameters)
            raise Exception("Must be exactly 4 parameters, {} given".format(l))

        name = connection.toStr(parameters[0])
        title = connection.toStr(parameters[1])
        ptype = connection.toStr(parameters[2])
        command = connection.toStr(parameters[3])

        connection.manager.server.processes.start_process(
            name,
            title,
            ptype,
            command
        )

        connection.writePackage(b"OK")

    @staticmethod
    def do_proclist(connection, parameters):
        """
        Show list of all processes
        parameters: showdead
        "showdead" - is a keyword, if is set, proclist would show processes
        that are already finished.
        Format of list is: one process per line, separated by "\n"
        process' line consists of `words` delimited by space characters
        name, title, processtype,
        """
        # TODO ДОПИСАТЬ СПРАВКУ ПРО ФОРМАТ ВЫДАЧИ ПРОЦЕССОВ

        need_showdead = Tools.list_item(parameters, 0) == b"showdead"
        result = connection.manager.server.processes.get_proc_list(need_showdead)
        connection.writePackage(result)

    @staticmethod
    def do_burndead(connection, parameters):
        """
        'Burn' dead processes (removes it from memory)
        no parameters
        """
        connection.manager.server.processes.burn_dead()

    @staticmethod
    def de_setvar(connection, parameters):
        """
        Set variables, attached to a process
        parameters: process_name variable_name=variable_value variable2_name=variable2_value
        example:
        'setvar my_long_process x=1 y=2'
        Variables not used anyhow by pdem server, it's just to store some information with the process.
        Variables' values are returned to the client by proclist command.
        """
        if len(parameters)==0:
            pass
        else:
            name = parameters[0]
            process = connection.manager.server.processes.get_proc_by_name(para)


class PdemServerApp():
    """
    Server application class. Link all parts together
    """

    # Конифгурация по умолчанию
    defaultConfig = {
        "logLevel": logging.DEBUG,  # уровень логирования
        "listenAddr": "127.0.0.1",  # IP-адрес на котором надо слушать
        "listenPort": 5555,         # порт на котором надо слушать
        "daemonize": False,          # после запуска демонизироваться
        "daemonLogFile": "/tmp/pdem-server.log"  # лог-файл для демона
    }

    def __init__(self, config=None):
        self.config = PdemServerApp.defaultConfig.copy()
        "При инициализации можно указать хэш настроек"
        if config is not None:
            self.set_config(config)
        self.logger = logging.getLogger('pdem')
        self.logger.setLevel(self.config['logLevel'])

        if self.config['daemonize']:
            self.logger.addHandler(
                logging.FileHandler(self.config['daemonLogFile'])
            )
        self.server = PdemServer()
        self.server.setPort(self.config['listenPort'])
        self.server.setAddr(self.config['listenAddr'])
        self.server.app = self

    def run(self):
        """
        Start server
        :return:
        """
        self.logger.info("Starting pdem server")
        try:
            # Если это возможно, запустим сервер
            self.server.run()
        except Exception as e:
            if e.errno == 98:
                self.logger.error(
                    "Error starting server on {}:{}, exiting".format(
                        self.config['listenAddr'], self.config['listenPort']
                    )
                )
            else:
                self.logger.error("Unhandled server error:" + str(e))
            return
        if self.config['daemonize']:
            try:
                self.logger.info("Daemonizing")
                if not os.path.exists(self.config['daemonLogFile']):
                    logFile = os.open(self.config['daemonLogFile'],
                                      os.O_WRONLY | os.O_CREAT)
                    logFile.write("")
                    logFile.close()
                self.daemonize(self.config['daemonLogFile'])
            except OSError as e:
                self.logger.error("Error daemonizing:" + str(e))

        self.logger.debug("Entering IOLoop")
        IOLoop.instance().start()

    def die(self):
        """
        Stop app and exit
        """
        self.logger.debug("Stop IOLoop")
        IOLoop.instance().stop()
        self.logger.debug("Stop and destroy tcp server")
        self.server.die()
        self.server.app = None
        del self.server
        self.server = None
        self.logger.info("Exiting pdem server")

    def daemonize(self, redirect_to="/dev/null"):
        """
        Detach a process from the controlling terminal and run it in the
        background as a daemon.
        Redirects output and input to redirect_to variable.
        """
        try:
            pid = os.fork()
        except OSError as e:
            raise Exception("%s [%d]" % (e.strerror, e.errno))

        if (pid == 0):  # The first child.
            os.setsid()
            try:
                pid = os.fork()	  # Fork a second child.
            except OSError as e:
                raise Exception("%s [%d]" % (e.strerror, e.errno))

            if (pid == 0): 	# The second child.
                os.chdir("/")
                os.umask(0)
            else:
                os._exit(0)  # Exit parent of the second child.
        else:
            os._exit(0)  # Exit parent of the first child.

        sys.stdout.flush()
        sys.stderr.flush()
        si = open(redirect_to, 'r')
        so = open(redirect_to, 'a+')
        se = open(redirect_to, 'a+')

        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

        return(0)

    def set_config(self, config):
        "Set config from 'config', overwriting default values"
        assert isinstance(config, dict)

        for key, value in config.items():
            if key in self.config:
                self.config[key] = value


class PdemConsole:
    """
    Reading config files and command line arguments class.
    """
    # Parameters, that could be saved into file
    writable_params = [
        "logLevel", "listenAddr", "listenPort", "daemonize", "daemonLogFile"
    ]

    # Parameters, that could be read from file
    readable_params = ["logLevel", "listenAddr", "listenPort",
                       "daemonize", "daemonLogFile", "conf"]

    # Strings for selecting logging level
    logLevelMap = {
        "DEBUG": logging.DEBUG, "INFO": logging.INFO,
        "ERROR": logging.ERROR, "WARINIG": logging.WARNING
    }

    def __init__(self):
        "Инициализация. Запишем здесь параметры по умолчанию"

        self.logger = logging.getLogger('pdem.PdemConsole')
        self.logger.setLevel(logging.INFO)

        # Оставшиеся аргументы командной строки (после вырезки параметров)
        self.other_arguments = []

        self.defaultConfig = {
            "command": "help",          # команда по умолчанию - справка
            "logLevel": logging.DEBUG,  # уровень логирования
            "listenAddr": "127.0.0.1",  # IP-адрес на котором надо слушать
            "listenPort": 5555,         # порт на котором надо слушать
            "daemonize": False,          # после запуска демонизироваться
            "daemonLogFile": "/tmp/pdem-server.log"  # лог-файл для демона
        }

    def validate(self, params):
        """
        Функция валидирует параметры, и бросает исключение,
        если параметр не валидирован из-за ошибки значения параметра.
        Если исключения не последовало - возвращается массив обработанных
        параметров
        """
        YesNoMap = {
            'yes': 1, 'true': 1, '1': 1, 'no': 0, 'false': 0, '0': 0
        }
        if 'logLevel' in params:

            if (params['logLevel'] not in PdemConsole.logLevelMap):
                if (
                        Tools.parseInt(params['logLevel']) in
                        PdemConsole.logLevelMap.values()):

                    params['logLevel'] = Tools.parseInt(params['logLevel'])
                else:
                    raise Exception(
                        "Parameter logLevel should be one of"
                        "the following values: " + ",".join(
                            PdemConsole.logLevelMap.keys()
                        ) + " but it's '" + str(params['logLevel']) + "'")
            else:
                params['logLevel'] = PdemConsole.logLevelMap[
                    params['logLevel']
                ]
        if 'daemonize' in params:
            daemonize = str(params['daemonize']).lower()
            if daemonize not in YesNoMap:
                raise Exception("Parameter daemonize should be one of the" +
                                " following values: " + ",".join(
                                    (YesNoMap.keys())
                                    ) + " but it's '" + daemonize + "'"
                                )
            else:
                params['daemonize'] = YesNoMap[daemonize]

        if 'listenPort' in params:
            try:
                port = int(params['listenPort'])
            except ValueError as e:
                raise Exception("Parameter listenPort should be integer, " +
                                "but it's '" + params['listenPort'] + "'")
            if port < 0 or port > 65535:
                raise Exception("Parameter listenPort should be in 0-65536, " +
                                "but it's '" + str(port) + "'")
            params['listenPort'] = port

        if 'listenAddr' in params:
            if params['listenAddr'] == "":
                params['listenAddr'] = None

        return params

    def read_config_file(self, path=None):
        """
        Функция считывает файл построчно,
        если строка начинается с "#" - она игнорируется как комментарий
        если в строке есть "=" то она разбивается на то что до и то что после,
        из обоих частей удаляются начальные и конечные пробелы и т.д. после
        чего данная строка добавляется в массив переменных.
        После этого производится валидация параметров, после чего в случае
        успеха возвращается массив считанных из файла и провалидированных
        параметров
        """
        fileConf = {}
        if path is None:
            path = os.path.expanduser("~/.config/pdem.conf")
        path = os.path.realpath(path)

        self.logger.debug("Reading conf file:" + path)

        if os.path.exists(path) and os.path.isfile(path):
            with open(path, "r") as f:
                data_lines = f.readlines()
            for line in data_lines:
                line = line.strip("\n ")
                if line[0:1:] == "#":
                    continue
                parts = line.split("=")
                if len(parts) < 2:
                    continue
                name = parts[0].strip()
                value = "=".join(parts[1::]).strip().strip('"')
                fileConf[name] = value
                # print(name + " => " + value)
        try:
            fileConf = self.validate(fileConf)
        except Exception as e:
            self.logger.error("Error in config file " + path + ":\n" + str(e) +
                              "\nParameters from the file are ignored")
            fileConf = {}

        return fileConf

    def write_config_file(self, params, path):
        s_params = params.copy()
        with open(path, "w") as f:
            f.write("# Configuration file generated by pdem-server" +
                    " writeconf command\n")
            for param in s_params:
                value = s_params[param]
                if param in PdemConsole.writable_params:
                    if param == "logLevel":
                        for p in PdemConsole.logLevelMap:
                            if PdemConsole.logLevelMap[p] == value:
                                value = p
                    f.write(param + " = " + str(value) + "\n")

    def read_arguments(self):
        "Считать аргументы командной строки"
        params = {}
        # Удалим первый элемент из аргументов, так как там указан сам скрипт
        arguments = sys.argv[1::]
        other_arguments = []

        if len(arguments):
            params['command'] = arguments[0]

        j = 0
        for i in range(len(arguments)):

            if j >= len(arguments):
                break

            arg = arguments[j]
            prevWasParam = False
            if arg[0:2:] == "--" and arg[2::] in PdemConsole.readable_params:
                paramName = arg[2::]
                if j+1 < len(arguments):
                    paramValue = arguments[j+1]
                    params[paramName] = paramValue
                    j += 1
            else:
                other_arguments.append(arg)

            j += 1

        params = self.validate(params)
        # Запомним оставшиеся аргументы
        self.other_arguments = other_arguments
        return params

    def get_params(self):
        arg_params = self.read_arguments()
        if ("conf" not in arg_params):
            arg_params['conf'] = None
        conf_params = self.read_config_file(arg_params['conf'])
        default_params = self.defaultConfig

        params = {}
        for key in default_params:
            params[key] = default_params[key]
            if key in conf_params:
                params[key] = conf_params[key]
            if key in arg_params:
                params[key] = arg_params[key]

        params = self.validate(params)

        return params


class PdemClient(object):
    """
    Класс клиента, используется для отправки данных клиенту
    и получения от него ответов
    """

    def __init__(self, host, port, autoIOLoop=False):
        """
        Конструктор
        host -- адрес хоста к которому подключаемся, например "127.0.0.1"
        port -- порт к которому подключаемся
        autoIOLoop -- автоматически создать IOLoop, нужно в том случае, если
                      используется вне какого-то другого IOLoop'а
        """
        self.host = host
        self.port = port
        self.loop = False
        self.autoIOLoop = autoIOLoop
        self.client = TCPClient()
        self.future_stream = self.client.connect(self.host, self.port)
        self.future_stream.add_done_callback(self._connected)
        self.command = None
        self.commandName = ""
        self.connected = False
        self.buffer = b""
        self.stream = None
        self.done_callback = None

    def _connected(self, future):
        try:
            self.stream = future.result()
        except Exception as e:
            if self.commandName == "status" or self.commandName == "do":
                print("pdem server isn't running")
                if self.autoIOLoop:
                    self._stop_ioloop()
            elif self.commandName == "stop":
                print("pdem server isn't running, so it cannot be stopped")
                if self.autoIOLoop:
                    self._stop_ioloop()
            else:
                print("Connection error:" + str(e))
            return

        self.stream.read_until_close(self._data_receive_done,
                                     self._data_receive)
        self.stream.set_close_callback(self._disconnect)
        self.connected = True
        self._run()

    def _data_receive_done(self, data):
        "Функция-заглушка"
        pass

    def _data_receive(self, data):
        self.buffer = self.buffer + data
        while self._try_to_cut_package():
            pass

    def _start_ioloop(self):
        if not self.loop:
            self.loop = True
            IOLoop.instance().start()

    def _stop_ioloop(self):
        if self.loop:
            IOLoop.instance().stop()
            self.loop = False

    def _add_command(self, command):
        self.commands.append(command)

    def _run(self):
        if len(self.command) > 0:
            command = self.command
            self._writeCommand(command)

    def _writeCommand(self, command):
        data = [Tools.addSlashes(item.encode("UTF-8")) for item in command]
        package = b" ".join(data)
        self.stream.write(b"[CMD[" + package + b"]CMD]")

    def _try_to_cut_package(self):
        "Попытка вырезать пакет из буфера данных"
        start = b"[ANS["
        end = b"]ANS]"
        start_pos = self.buffer.find(start)
        if (start_pos > -1):
            if (start_pos > 0):
                self.buffer = self.buffer[start_pos::]
            end_pos = self.buffer.find(end)
            if (end_pos > -1):
                package = self.buffer[len(start):end_pos:]
                self.buffer = self.buffer[end_pos + len(end)::]
                self._parse_package(package)
                return True
        return False

    def _parse_package(self, package):
        if self.commandName == 'stop':
            if self.autoIOLoop:
                self._stop_ioloop()
        elif self.commandName == 'status':
            if self.autoIOLoop:
                self._stop_ioloop()
            print("pdem server is running")
        elif self.commandName == "do":
            if self.autoIOLoop:
                self._stop_ioloop()
            if isinstance(self.done_callback, collections.Callable):
                self.done_callback(package)
            else:
                print("pdem server answer:\n" + package.decode("UTF-8"))
        else:
            print("Command " + self.commandName +
                  " not supported in _parse_package yet")

    def _disconnect(self):
        """
        Функция вызывается при обрыве соединения
        """
        if self.commandName == "stop":
            print("pdem server successfully stopped")
        if self.autoIOLoop:
            IOLoop.instance().stop()

    def stop(self):
        self.command = ["quit"]
        self.commandName = "stop"
        if self.connected:
            self._run()
        if self.autoIOLoop:
            self._start_ioloop()

    def do(self, cmd_and_args, callback=None):
        self.command = cmd_and_args
        self.done_callback = callback
        self.commandName = "do"
        if self.connected:
            self._run()
        if self.autoIOLoop:
            self._start_ioloop()

    def status(self):
        self.command = ["proclist"]
        self.commandName = "status"
        if self.connected:
            self._run()
        if self.autoIOLoop:
            self._start_ioloop()


def main():
    "Основная функция"
    # params = read_params()

    console = PdemConsole()

    params = console.get_params()

    def print_params(params):

        printedParams = params.copy()

        del printedParams['command']

        if "conf" in printedParams:
            del printedParams['conf']

        if "command" in printedParams:
            del printedParams['command']

        if "logLevel" in printedParams:
            for name in PdemConsole.logLevelMap:
                if printedParams['logLevel'] == PdemConsole.logLevelMap[name]:
                    printedParams['logLevel'] = name
                    break

        paramsStr = '\n'.join([' : '.join(("  " + k, str(printedParams[k])))
                              for k in printedParams])

        print(paramsStr)

    if params['command'] == 'help':
        print(Tools.stripLines("""
                pdem-server is a process demonizer server, controlled through
                simple tcp protocol, and used to run long processes, trace
                their state, and return this information to the client.
                USAGE:

                {} [command] [parameters]

                Commands:

                help                displays this help screen (used by default)

                start [parameters]  start pdem server
                .                   would use parameters, when config file, and
                .                   when default config options

                stop  [parameters]  stop running instance of pdem server
                .                   will use parameters to determine where does
                .                   server running, and send "stop" command to
                .                   it as a client.

                status [parameters] get status of working (or not)pdem instance
                .                   will use parameters to determine where does
                .                   server running (or should running) and
                .                   get info from it by a client requests

                writeconf /path/to  write default configuration to a file

                do command [space separated arguments] [parameters]
                .                   connect to a server as a client, send
                .                   command, return an answer and exit
                .                   'command' is one of the supported commands
                .                   command "help" will give you instructions
                .                   [arguments] depends on entered command

                Parameters:

                --conf /path/to    specify config file, where to get parameters
                --listenAddr IP    specify address of interface where to listen
                --listenPort PORT  specify port which should be listened
                --daemonize Yes    if "yes","true" or "1", will be demonized
                --logLevel LEVEL   logLevel, one of DEBUG, INFO, WARNING, ERROR
                --daemonLogFile /path specify file where to put log if daemon

                When "start", "stop" or "status" commands are runned, config
                options are used in this priority:
                command line parameters > config file > default options

              """.format(os.path.basename(sys.argv[0]))))

    if params['command'] == 'start':
        print("Starting pdem-server with parameters:")
        print_params(params)
        app = PdemServerApp(params)
        app.run()

    elif params['command'] == 'stop':
        print("Stopping pdem-server with parameters:")
        print_params(params)
        c = PdemClient(params['listenAddr'], params['listenPort'], True)
        c.stop()

    elif params['command'] == 'status':
        print("Status of pdem-server with parameters:")
        print_params(params)
        c = PdemClient(params['listenAddr'], params['listenPort'], True)
        c.status()

    elif params['command'] == 'writeconf':
        if "conf" not in params:
            params['conf'] = "/tmp/pdem-server.conf.example"
        print("Configuration to be written:")
        print_params(params)
        print("File to be written:" + params['conf'])
        console.write_config_file(params, params['conf'])
    elif params['command'] == 'do':
        # Возьмём "остальные" аргументы (не являющиеся параметрами)
        # удалив из них первый (="do")
        arguments = console.other_arguments[1::]
        c = PdemClient(params['listenAddr'], params['listenPort'], True)
        c.do(arguments)
    else:
        print("Command '" + params['command'] + "' is unknown, use:\n" +
              os.path.basename(sys.argv[0]) + " help"+"\n" + "to get help")


if __name__ == '__main__':
    main()
