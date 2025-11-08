* 2025-11-08 OpenAI <opensource@openai.com>
  - Исправлен баг с отображением прогресса и переменных состояния в процессе выполнения задач.

* 2025-11-07 OpenAI <opensource@openai.com> 1.0.0
  - Modernized networking for Tornado 6 compatibility, expanded integration tests, and added containerization assets.

* 2016-11-18 mihanentalpo <mihanentalpo@yandex.ru> 0.1.5
  - Fixed bugs in package

* 2016-10-30 mihanentalpo <mihanentalpo@yandex.ru> 0.1.4
  - Finished python3 implementation, and uploaded pypi package "pdem"

* Sun Sep 08 2013 mihanentalpo <mihanentalpo@yandex.ru> 0.0.12
  - AFixed bug - when some of process' vars contain newline symbol it lead to a broken output. Now, '\n' converted to '\\n'.

* Mon May 27 2013 mihanentalpo <mihanentalpo@yandex.ru> 0.0.11
  - added functionality to see old dead processes, by send "proclist showdead", and remove them by send "burndead"

* Sat May 25 2013 mihanentalpo <mihanentalpo@yandex.ru> 0.0.10
  - fixed bug with stack opverflow in case of lots of incoming process'es data. But now it will consume more CPU.

* Thu Feb 28 2013 mihanentalpo <mihanentalpo@yandex.ru> 0.0.8
  - added daemonization config option

* Wed Feb 27 2013 mihanentalpo <mihanentalpo@yandex.ru> 0.0.5
  - added [PDEM[var:x=y]PDEM]

* Tue Feb 26 2013 mihanentalpo <mihanentalpo@yandex.ru> 0.0.4
  - working release

* Wed Feb 20 2013 mihanentalpo <mihanentalpo@yandex.ru> 0.0.3
  - First alpha release

