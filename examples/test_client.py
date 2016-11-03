# Подключаем модуль
from pdem import pdem
import os
# Создаём клиент, и подключаемся (последний параметр = True если вы не используете в своём проекте tornado и его ioloop)
client = pdem.PdemClient("127.0.0.1", 5555, True)
# Запускаем скрипт test_script.sh
path = os.path.realpath(os.path.curdir + "/bash/test_script.sh")
path2 = os.path.realpath(os.path.curdir + "/bash/test_script2.sh")

def proclist_result(result):
    processes = [pdem.Tools.explode_by_spaces(x) for x in result.decode("UTF-8").split("\n")]
    print(processes)



client.runprocess("test_script", "Тестовый скрипт", path)
client.runprocess("test_script2", "Тестовый скрипт2", path2)
client.proclist(lambda res:print(res))
