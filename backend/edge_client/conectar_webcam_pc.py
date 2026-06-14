import base64
import time
import os
import subprocess
import cv2
from google.cloud import pubsub_v1
from google.cloud import firestore

# Mock del hardware. Como estamos corriendo esto en local (PC/Mac), no hay pines GPIO.
# Sustituimos el envío de señales PWM al servo por prints en consola para poder 
# depurar la máquina de estados sin depender del robot físico.
ANGULO_INICIAL = 190 

def set_angulo(angulo):
    print(f"  [SIMULADOR MOTOR] Moviendo a {angulo} grados...")

def soltar_motor():
    print("  [SIMULADOR MOTOR] Motor relajado (Duty 0).")

print(f"Ajustando dispensador simulado a su posicion inicial: {ANGULO_INICIAL} grados")
set_angulo(ANGULO_INICIAL)
time.sleep(1.0)  
soltar_motor()   

# Timers de control de estado. 
# El cooldown evita que el dispensador se vuelva loco y vacíe el depósito 
# si el animal decide quedarse sentado delante de la cámara 5 minutos seguidos.
ultimo_premio_tiempo = 0.0
COOLDOWN_PREMIOS = 30.0  

ultimo_audio_tiempo = 0.0 
VENTANA_OBEDIENCIA = 15.0 

# Variables de entorno para Google Cloud
PROJECT_ID = "petwatch-sm"
DATABASE_ID = "petwatch-db"
TOPIC_ID = "petwatch-video-stream"


def escuchar_comandos_manuales(documentos_totales, cambios, hora_lectura):
    # Callback asíncrono para el botón manual de Flutter. 
    # Esta función hace bypass a la IA: tira el premio independientemente de la postura.
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            
            # Chequeo de idempotencia vital: evita que tiremos un premio viejo 
            # al reiniciar el script si se quedó colgado en la base de datos.
            if datos.get('completado') is False:
                print("\n[MANUAL] Comando recibido desde la App. Activando dispensador simulado...")
                try:
                    set_angulo(45)
                    time.sleep(1.5)
                    set_angulo(ANGULO_INICIAL)
                    time.sleep(1.5)
                    soltar_motor()
                    print("[DISPENSADOR MANUAL] Premio entregado con exito.")
                except Exception as servo_error:
                    print(f"[DISPENSADOR MANUAL] Error simulado: {servo_error}")

                # Bloqueamos el documento para no volver a consumirlo
                cambio.document.reference.update({'completado': True})
                print("[DATABASE] Comando manual marcado como leido.")


def reproducir_audio(documentos_totales, cambios, hora_lectura):
    # Listener para descargar y reproducir las notas de voz en el PC.
    global ultimo_audio_tiempo
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            
            if datos.get('reproducido') is False:
                print("\n[ALTAVOZ PC] Entrando audio desde la web PetWatch")
                audio_b64 = datos.get('audio_b64')
                
                if audio_b64:
                    archivo_entrada = "mensaje_web.webm"
                    archivo_salida = "mensaje_pc.wav"
                    
                    # Firebase solo traga texto, así que el audio viene en Base64. 
                    # Lo reconstruimos a un binario jugable.
                    bytes_audio = base64.b64decode(audio_b64)
                    with open(archivo_entrada, "wb") as archivo_webm:
                        archivo_webm.write(bytes_audio)
                    
                    try:
                        subprocess.run(['ffmpeg', '-i', archivo_entrada, '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2', archivo_salida, '-y', '-loglevel', 'quiet'], check=True)
                        print("Reproduciendo audio por los altavoces del ordenador...")
                        
                        # OJO: Cambiamos 'aplay' por 'ffplay'.
                        # Aplay solo existe en Linux (ALSA). Ffplay funciona nativo en Windows y Mac,
                        # permitiéndote escuchar los audios sin instalar controladores raros.
                        subprocess.run(['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', archivo_salida])
                        print("[ALTAVOZ PC] Mensaje emitido.")
                        
                        # Disparamos el cronómetro. A partir de aquí la IA empieza a juzgar al animal.
                        ultimo_audio_tiempo = time.time()
                        print(f"[ADIESTRAMIENTO] La mascota tiene {VENTANA_OBEDIENCIA} segundos para sentarse frente a la webcam.")
                        
                    except Exception as e:
                        # Si revienta aquí, suele ser porque la variable de entorno de ffmpeg no está configurada en Windows
                        print(f"[ALTAVOZ PC] Error en la reproduccion: Verifica tener ffmpeg/ffplay en el PATH. {e}")
                    finally:
                        # Garbage collection manual para no saturar el disco duro con .wavs temporales
                        if os.path.exists(archivo_entrada): os.remove(archivo_entrada)
                        if os.path.exists(archivo_salida): os.remove(archivo_salida)

                cambio.document.reference.update({'reproducido': True})


def evaluar_premios(documentos_totales, cambios, hora_lectura):
    # Motor de adiestramiento. Cruza los datos de Cloud Vision con el estado de nuestro altavoz.
    global ultimo_premio_tiempo, ultimo_audio_tiempo
    
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            animal_detectado = str(datos.get("animal", "")).lower()
            postura_detectada = str(datos.get("postura", "")).upper()
            
            if animal_detectado in ["dog", "cat"] and postura_detectada == "SENTADO":
                tiempo_actual = time.time()
                
                # Regla 1: Solo hay premio si ha habido un comando de voz previo en los últimos 15s.
                if (tiempo_actual - ultimo_audio_tiempo) <= VENTANA_OBEDIENCIA:
                    
                    # Regla 2: Respetar el cooldown del motor físico.
                    if tiempo_actual - ultimo_premio_tiempo >= COOLDOWN_PREMIOS:
                        ultimo_premio_tiempo = tiempo_actual
                        
                        # Cortamos la ventana a cero. Si no hacemos esto, el sistema le podría dar 
                        # 3 premios seguidos dentro de la misma ventana de 15 segundos.
                        ultimo_audio_tiempo = 0.0 
                        
                        print(f"\n[IA] {animal_detectado.upper()} obedecio tu comando y esta SENTADO. Dando premio virtual...")
                        try:
                            set_angulo(90)
                            time.sleep(1.5)
                            set_angulo(45)
                            time.sleep(1.5)
                            set_angulo(ANGULO_INICIAL)
                            time.sleep(1.5)
                            soltar_motor()
                            print("[DISPENSADOR] Recompensa virtual entregada.")
                        except Exception as servo_error:
                            print(f"[DISPENSADOR] Error: {servo_error}")
                    else:
                        segundos = int(COOLDOWN_PREMIOS - (tiempo_actual - ultimo_premio_tiempo))
                        print(f"\r[INFO] Mascota sentada, pero dispensador en cooldown. Faltan {segundos}s.", end="", flush=True)


def main():
    print("Iniciando PETWATCH Simulador Edge (PC Local)...")

    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
    except Exception as e:
        print(f"Error critico en Pub/Sub: {e}")
        return

    try:
        db = firestore.Client(project=PROJECT_ID, database=DATABASE_ID)
    except Exception as e:
        print(f"Error critico en Firestore: {e}")
        return

    print("Inicializando hardware de camara (Webcam PC)...")
    # Sustituimos Picamera2 por cv2 para poder capturar desde la webcam integrada del portátil
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: No se pudo encender la camara web de tu ordenador. Revisa permisos del SO.")
        return

    # Enganchamos los listeners en hilos separados manejados por el SDK de Google
    db.collection("comandos_audio").on_snapshot(reproducir_audio)
    db.collection("comandos_servo").on_snapshot(escuchar_comandos_manuales)
    db.collection("historial_mascotas").on_snapshot(evaluar_premios)

    print("Sistema operativo. Transmitiendo telemetria de la webcam y esperando eventos...")
    print("TIP: Pon el movil con una foto de un perro frente a la webcam despues de enviarle un audio.")

    ultimo_envio_ia = 0.0

    try:
        while True:
            # Captura un frame crudo (matriz numpy) de la webcam
            ret, frame_bgr = cap.read()
            if not ret:
                continue

            tiempo_actual = time.time()
            # Throttling: Limitamos el upload a ~5 fps. 
            # Subir video sin limite saturaria Pub/Sub al instante y agotaria la cuota gratuita.
            if tiempo_actual - ultimo_envio_ia >= 0.2:
                # Comprimir a JPG no es negociable; el payload debe pesar poco para que no haya lag
                _, buffer = cv2.imencode('.jpg', frame_bgr)
                img_bytes = buffer.tobytes()

                try:
                    future = publisher.publish(topic_path, img_bytes)
                    print(f"\r[VÍDEO PC] Subiendo frame... ID: {future.result()[:15]}...", end="", flush=True)
                    ultimo_envio_ia = tiempo_actual
                except Exception as pub_error:
                    print(f"\nError de subida a Pub/Sub: {pub_error}")

            # Desahoga el hilo principal para evitar que la CPU del PC se ponga al 100%
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nApagado manual detectado (Ctrl+C).")
    finally:
        print("Liberando webcam y cerrando procesos...")
        cap.release()
        print("Apagado completado. Entorno de pruebas cerrado.")

if __name__ == "__main__":
    main()