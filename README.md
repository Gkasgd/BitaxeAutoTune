# BitaxePID Auto-Tuner

## Overview
Es una modificación vibe codeada para de BitaxePID, este programa busca obtener
el mejor rendimiento de la bitaxe gamma 601 a través de los parámetros configurados
nunca superando la Temperatura asignada, una vez llegado al máximo de frecuencia,
sin sobrepasar la temperatura, ajusta el voltaje para usar la menor cantidad de
energía posible, sin sobrepasar la cantidad de errores especificada por el usuario.

## USAR BAJO SU PROPIO RIESGO
El programa le faltan algunas comprobaciones de seguridad
Por ejemplo, que pasaría si el chip sube de temperatura de golpe.

Este programa ha sido y sigue siendo testeado por mi con una Bitaxe Gamma 601,
con dos disipadores de calor pequeños de aluminio en el regulador de voltaje,
con un fan de 12v apuntando directamente a ellos, con un fan 12v para el ASIC,
con GND compartido entre el Bitaxe y la fuente del FAN, conectado al control
PWM de la placa para poder manejar su velocidad.

## CONSIDERACIÓN
El archivo que uso para su configuración es: SAFE-BM1370-estabilidad.yaml
El hashrate objetivo NO IMPORTA, lo que importa es la TEMPERATURA, la FRECUENCIA, el VOLTAJE y la tasa de ERROR.
Recomiendo dejar el FAN del ASIC en una velocidad fija, ya que el programa mismo busca la temperatura objetivo,
por lo que el FAN del ASIC va a quedar al 100% si lo dejan en AUTO en la configuración de AxeOS.
El programa corre en un servidor de Umbrel dentro de la misma red que la Bitaxe, ya que éste a demostrado su operatividad 24/7 durante años.
En la configuración se puede DESACTIVAR LA MEDICIÓN DE POOLS Y SU POSTERIOR CONFIGURACIÓN, usando las que ya tenés cargadas en las Bitaxe.

## USO
copia los archivos a tu umbrel por ejemplo. Si estás en windows te va a servir

scp -r "El directorio/enWindows" umbrel@tuip.com:~/BitaxePID

cd ~/BitaxePID

BITAXEPID_MINER_IP=LA IP DE TU BITAXE docker compose up -d --build #LA PRIMERA VEZ

docker compose up -d --build #SI HACES ALGUN CAMBIO
______________________________
docker compose down     # parar

docker compose up -d    # arrancar

docker compose logs -f  # ver qué hace (Ctrl+C solo sale del log)
__________________________
los cambios se hacen aquí

nano ~/BitaxePID/SAFE-BM1370-estabilidad.yaml

<img width="1106" height="267" alt="{6C70C8A8-B84D-4ABD-8C03-DBFB2B987844}" src="https://github.com/user-attachments/assets/b04b3db1-5489-4345-b4dc-492dadd4d95f" />

<img width="1876" height="939" alt="{B745F054-2446-4075-9851-5827AB933948}" src="https://github.com/user-attachments/assets/99db3717-d58b-4fbd-b69a-90a6f41bd97c" />

Acepto cualquier donación, ya que realmente me está sirviendo este programa y gasté un par de sats en vibecodearlo, muchas gracias por leer hasta aqúi.

### BOLT12 OFFER:
***lno1pgqppmsrse80qf0aara4slvcjxrvu6j2rp5ftmjy4yntlsmsutpkvkt6878syu9rkvrla9j0ec7rgwvm4hkwp9049jmpsj8cesjne4negyt0ux9wqgp70pyulexvmz54jvwhr4pxwhfzlpgkr625rgmkwmc4zdhwzvf9ceqqxw0jfn0e4du6z8aejprzmavglqppt0l4mc0aztg0nud0lfja5s6f3x968z0eefmnntvwlg7nw8lekhwfcctq98jtw3thaasw7l3e4ryvluh5p6ju9dlxdtnlsfwhawe46r3gn5ddqqexgazuue69v5j42zqp688lyx9y6h5g2fghsfmeeavwrsrjm8zz3fpn2w0newtwhe8fh7st0lz6058mceqs***

### Bitcoin URI:
***bitcoin:?lno=lno1pgqppmsrse80qf0aara4slvcjxrvu6j2rp5ftmjy4yntlsmsutpkvkt6878syu9rkvrla9j0ec7rgwvm4hkwp9049jmpsj8cesjne4negyt0ux9wqgp70pyulexvmz54jvwhr4pxwhfzlpgkr625rgmkwmc4zdhwzvf9ceqqxw0jfn0e4du6z8aejprzmavglqppt0l4mc0aztg0nud0lfja5s6f3x968z0eefmnntvwlg7nw8lekhwfcctq98jtw3thaasw7l3e4ryvluh5p6ju9dlxdtnlsfwhawe46r3gn5ddqqexgazuue69v5j42zqp688lyx9y6h5g2fghsfmeeavwrsrjm8zz3fpn2w0newtwhe8fh7st0lz6058mceqs***

### Lightning Address: 
***irisnephew09@phoenixwallet.me***

### BTC Address: 
***bc1qatdwu9mrx4uq8sslhex8gsg5lk39cyxvu3y0lxplk46vxdzmgmpqjsqg93***
