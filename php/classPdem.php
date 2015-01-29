<?php

/**
 * Fully static class, to communicate with pdem daemon
 */
class pdem
{
	private static $conn_socket=0;
	private static $connected=false;
	private static $buff='';
	private static $procs=false;

	/**
	 *  @return integer возвращает номер сокета если соединение удалось установить
	 */
	static function connect($host,$port=5555,&$errno=0,&$errstr="")
	{
		self::$buff='';
		self::disconnect();
		self::$conn_socket = @fsockopen($host,$port,$errno,$errstr);
		if ($errno==0) self::$connected=true;
		return self::$conn_socket;
	}

	/**
	 *  отключиться
	 */
	static function disconnect()
	{
		if (self::$connected) fclose($conn_socket);
	}

	
	private function __construct(){}

	/**
	 *  Возвращает список процессов со всеми их внутренними данными.
	 *  @param boolean $forceRefresh - заставляет заново обратиться к серверу
	 *  @param string $filter_regex - регулярное выражение
	 *  @return array массив ключи которого - имена процессов, а значения - массивы данных по каждому из процессов. Среди данных - имя, заголовок, тип и т.д.
	 */ 
	static function proclist($forceRefresh=false,$filter_regex="",$showDead=false)
	{
		//Определение именованных параметров процесса в порядке их расположения в строке выдачи
		$map = array('name','title','type','cmd','lifetime','supportsprogress','progress','timeestimated');
		//Определение имен параметров, являющихся переменными, и выдаваемых в виде name=value
		$vars = array_flip(array('supportsprogress','progress','timeestimated'));

		if (self::$procs===FALSE || $forceRefresh)
		{
		      
			$data = self::raw_request('proclist' . ($showDead ? ' showdead' : ''));

			if ($data=='0')
			{
				self::$procs = array();
			}
			else
			{
				self::$procs=array();
				$lines = explode("\n",$data);
				foreach($lines as $line)
				{
					$item = array();
					//echo $line;
					$line_items = self::spExplode($line);
					//print_r($line_items);
					foreach($line_items as $key=>$val)
					{
						if (isset($map[$key]))
						{
							//Если это - переменная
							if (isset($vars[$map[$key]]))
							{
								$val = preg_replace("#" . $map[$key] . "\ ?=\ ?#i","",$val);
							}

							//echo $key . "(" . $map[$key] . ")=" . $val . "<br>";

							if (!isset($item[$map[$key]]))
							{ $item[$map[$key]] = $val;}


							//echo "\nITEM[" . $map[$key] . "]=".$item[$map[$key]] . "\n";
						}
						else if($val=='alive')
						{
							$item['alive']=true;
						}
						else if($val=='dead')
						{
							$item['alive']=false;
						}
						else
						{
                                                        $pair = explode("=",$val);
                                                        if (count($pair)>1)
                                                        {
                                                            $item['other'][$pair[0]] = $pair[1];
                                                        }
						}
					}

					if (isset($item['name']) && $item['name']!='')
					{
						self::$procs[$item['name']] = $item;
					}
				}


			}
		}


		$procs = self::$procs;

		if ($filter_regex!='')
		{
			$fprocs = array();
			foreach($procs as $name=>$val)
			{
				if (preg_match($filter_regex,$name))
				{
					$fprocs[$name] = $val;

				}
			}
			$procs = $fprocs;
		}

		return $procs;
	}

	/**
	 *  Убивает кучу процессов, имена которых совпадают по регулярному выражению
	 */ 
	static function killall($nameRegex='')
	{
		$procS = self::proclist(true,$nameRegex);
		$k = array();
		foreach($procS as $proc)
		{
			$k[] = $proc['name'];
		}
		self::kill($k);
	}

	/**
	 *  Убивает один или несколько процессов
	 *  @param array|string $procS имя одного процесса, либо массив имен убиваемых процессов
	 */ 
	static function kill($procS)
	{
		$arr = array("kill");
		if (is_array($procS))
		{
			$arr = array_merge($arr,$procS);
		}
		else
		{
			$arr[] = $procS;
		}
		return self::raw_request($arr);
	}

	/**
	 * Запускает bash-команду
	 */ 
	static function runLocal($name,$title,$shellcmd)
	{
		return self::raw_request(array("runprocess",$name, $title,"local",$shellcmd));
	}

	/**
	 *  Запускает http-get запрос
	 */ 
	static function runHttp($name,$title,$url)
	{
		return self::raw_request(array("runprocess",$name, $title,"http",$url));
	}

	/**
	*  Заставляет pdem уничтожить информацию о мертвых процессах
	*/ 
	static function burnDead()
	{
	    return self::raw_request(array('burndead'));
	}
	
	/**
	 *  ВЫполняет разбивку строки, заданной в формате синтаксиса [CMD[, [ANS[, или [PDEM[ - то есть набора слов разбитых пробелами
	 */ 
	static function spExplode($str)
	{
		$l = strlen($str);
		$prevslash = false;
		$parts = array('');
		$curpart = 0;
		for($i=0;$i<$l;$i++)
		{
			$m = substr($str,$i,1);
			//Если это пробел а перед ним не было слеша
			if ($m==' ' && !$prevslash)
			{
				$curpart++;
				$parts[$curpart]='';
			}
			//Если это пробел а перед ним был слеш
			elseif ($m==' ' && $prevslash)
			{
				$parts[$curpart] .= " ";
				$prevslash=false;
			}
			//Если это слэш а перед ним был слэш
			elseif ($m=="\\" && $prevslash)
			{
				$parts[$curpart] .= "\\";
				$prevslash=false;
			}
			//Если это слэш, а перед ним слэша не было
			elseif ($m=="\\" && (!$prevslash))
			{
				$prevslash=true;
			}
			//Если это ничего из вышеперечисленного, и перед ним был слэш:
			elseif ($prevslash)
			{
				$parts[$curpart] .= "\\" . $m;
				$prevslash=false;
			}
			//Если это ничего из вышеперчисленного
			else
			{
				$parts[$curpart] .= $m;
			}
		}
		return $parts;
	}
	
	/**
	 *  Функция для вывода сообщения "[PDEM[progressenabled]PDEM]"
	 */ 
	static function console_progress_enabled()
	{
		echo "[PDEM[progressenabled]PDEM]";
	}
	
	
	/**
	 *  Функция для вывода прогресса
	 */ 
	static function console_progress($progress)
	{
		$progress = (int)$progress;
		if ($progress < 0) $progress = 0;
		if ($progress > 100) $progress = 100;
		
		echo "[PDEM[progress={$progress}]PDEM]";
	}

	/**
	 *  Функция для вывода одной переменной [PDEM[var:name=value]PDEM]
	 */ 
	static function console_var($name,$value)
	{
		echo "[PDEM[var:{$name}={$value}]PDEM]";
	}

	/**
	 *  Функция для вывода набора переменных из массива 
	 */ 
	static function console_vars($vars)
	{
		foreach($vars as $name=>$value)
		{
			self::console_var($name,$value);
		}
	}

	/*	 
	 * Отправить запрос в виде "сырых данных"
	 * @param string|array $data Если строка - отправляется в обрамлении [CMD[ ]CMD],
	 *                           если массив - превращается в строку разбиваемую пробелами, внутренние пробелы элементов заменяются на "\ "
	 */
	static function raw_request($data,$timeout_sec=2)
	{
		//echo "-------------------------- RAW REQUEST ---------------------------\n";
		if (!self::$connected) return false;

		//Если это массив - значит это массив параметров
		if (is_array($data))
		{
			$strdata='';
			foreach($data as $item)
			{
				if (!is_array($item))
				{
					if ($strdata!='') $strdata .= " ";
					$strdata .= str_replace(" ","\\ ",str_replace("\\","\\\\",$item));
				}
			}

			$data = $strdata;
		}

		$tm = time();


		self::$buff="";

		$data = '[CMD[' . $data . ']CMD]';
		//echo $data;
		fwrite(self::$conn_socket, $data);

		while (!feof(self::$conn_socket))
		{
			$x = fread(self::$conn_socket, 65535);
			self::$buff .=$x;
			//echo $x;
			//echo "[" . feof(self::$conn_socket) . "]";

			$p0 = strpos(self::$buff,'[ANS[');
			$p1 = strpos(self::$buff,']ANS]');
			//echo "[".$p0."]";
			//echo "[".$p1."]";
			if ($p0!==FALSE && $p1!==FALSE)
			{
				$part = substr(self::$buff,$p0+5,strlen(self::$buff)-10);
				self::$buff = substr(self::$buff,$p1+5,strlen(self::$buff)-$p1-5);

				return $part;
			}
			if (time() -  $tm >= $timeout_sec) return "";
		}
		return $result;
	}
}




//Тестирование:


/*
if (!pdem::connect('192.168.1.10','5555'))
{

	//echo pdem::raw_request('proclist');

	$procs = pdem::proclist();
	$procs = array_keys($procs);
	pdem::kill($procs);

	//pdem::connect('127.0.0.1','5555');
	//echo pdem::runHttp("test1","Тест1","http://suslik.artfactor/test.php");
	echo pdem::runHttp("test1","Тест1","http://suslik.artfactor/test.php");
	//echo pdem::runHttp("test2","Тест2","http://suslik.artfactor/test.php");
	//echo pdem::runHttp("test3","Тест3","http://suslik.artfactor/test.php");
	//echo pdem::runHttp("Ltest1","Тест4","http://suslik.artfactor/test.php");
	//echo pdem::runHttp("Ltest2","Тест5","http://suslik.artfactor/test.php");
	//echo pdem::runLocal("SiteMap","Карта сайта Жалюзи","/home/mihanentalpo/gambas/pdem/bash/wget_loop.sh http://www.topper.spb.ru/af_sitemapper/sitemapper.php");

	//pdem::disconnect();

	$i=0;



	do
	{
		$i++;
		//pdem::connect('127.0.0.1','5555');
		$data = pdem::proclist(true);
		//pdem::disconnect();
		print_r($data);
		if ($i>5) pdem::killall("#test1#");
		//print_r(pdem::proclist(true));
		//$m = end($data);
		//echo $m['name'] . ":" . $m['progress'] . "%\n";
		sleep(1);
	}
	while(count($data)>0);

}
else
{
	echo "cannot connect\n";
}

*/
