=========================
pdem - Process Daemonizer
=========================

Purpose
-------

A tool, consists of server and client, used to run long processes, collect information from the processes, such as
progress and time elapsed and astimated.
Client could command to run process, kill process, get info about live or already dead process.

Install
-------

::
    # pip3 install pdem


Usage of library
----------------

Write config file to ~/.config/pdem-server.conf

::
    $ pdem-server writeConf --conf ~/.config/pdem-server.conf --daemonize Yes --logLevel WARNING --daemonLogFile /tmp/pdem.log

Start server with default params, or by params, written to ~/.config/pdem-server.conf:

::
    $ pdem-server start

Status of server:

::
    $ pdem-server status

Stop server:

::
    $ pdem-server stop

Display help:

::
    $ pdem-server help

Display help on

Run as client, send command to server, display result and exit:

display list of running processes:
::
    $ pdem-server do proclist

display list of running and dead processes:
::
    $ pdem-server do proclist showdead

run process by a server (bash0 would became it's identifier, "name"):
::
    $ pdem-server runprocess bash0 bash_interpreter local /bin/bash

kill running process by a server:
::
    $ pdem-server kill bash0





