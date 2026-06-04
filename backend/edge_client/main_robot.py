import base64
import time
import os
import subprocess
import cv2
from google.cloud import pubsub_v1
from google.cloud import firestore
from picamera2 import Picamera2

# ================= CONFIGURACIÓN MASTER =================
PROJECT_ID = "petwatch-sm"
DATABASE_ID = "petwatch-db"
TOPIC_ID = "petwatch-video-stream"
RTSP_URL = "rtsp://localhost:8554/mascota"
ANCHO = 640
ALTO = 480
FPS = 25
# ========================================================


def reproducir_audio(documentos_totales, cambios, hora_lectura):
    """
    Se ejecuta AUTOMÁTICAMENTE en un hilo secundario cada vez que entra 
    un audio nuevo desde la aplicación web de Flutter.
    """
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            
            if datos.get('reproducido') is False:
                print("\n🎤 [ALTAVOZ] ¡Entrando audio desde la web PetWatch!")
                audio_b64 = datos.get('audio_b64')
                
                if audio_b64:
                    archivo_entrada = "mensaje_web.webm"
                    archivo_salida = "mensaje_robot.wav"
                    
                    bytes_audio = base64.b64decode(audio_b64)
                    with open(archivo_entrada, "wb") as archivo_webm:
                        archivo_webm.write(bytes_audio)
                    
                    try:
                        # --- CONVERSIÓN CON FFMPEG ---
                        subprocess.run([
                            'ffmpeg', '-i', archivo_entrada, 
                            '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2',
                            archivo_salida, '-y', '-loglevel', 'quiet'
                        ], check=True)
                        
                        # --- REPRODUCCIÓN DIRECTA AL AMPLIFICADOR I2S (TARJETA 2) ---
                        print("🔊 Enviando audio directo a los pines del amplificador (Tarjeta 2)...")
                        subprocess.run(['aplay', '-D', 'plughw:2,0', archivo_salida], check=True)
                        print("✅ [ALTAVOZ] Mensaje emitido correctamente por el hardware.")
                        
                    except subprocess.CalledProcessError:
                        print("❌ [ALTAVOZ] Error: FFMPEG o APLAY fallaron al procesar el archivo.")
                    except Exception as audio_error:
                        print(f"❌ [ALTAVOZ] Error crítico en la reproducción: {audio_error}")
                    finally:
                        if os.path.exists(archivo_entrada): os.remove(archivo_entrada)
                        if os.path.exists(archivo_salida): os.remove(archivo_salida)

                cambio.document.reference.update({'reproducido': True})
                print("📌 [DATABASE] Documento marcado como leído en Firestore.\n")


def main():
    print("==================================================")
    print("       PETWATCH CLOUD - SISTEMA INTEGRADO         ")
    print("==================================================")

    # 1. Conexión con Google Cloud Pub/Sub
    print("Conectando con Google Cloud Pub/Sub...")
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
        print("-> [OK] Conexión Pub/Sub establecida.")
    except Exception as e:
        print(f"Error al conectar con Pub/Sub: {e}")
        return

    # 2. Conexión con Google Cloud Firestore
    print("Conectando con Google Cloud Firestore...")
    try:
        db = firestore.Client(project=PROJECT_ID, database=DATABASE_ID)
        print("-> [OK] Conexión Firestore establecida.")
    except Exception as e:
        print(f"Error al conectar con Firestore: {e}")
        return

    # 3. Configurar FFmpeg Subprocess para el Vídeo en Directo (Hacia MediaMTX)
    print("Iniciando codificador multimedia (Tubería de vídeo)...")
    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24',                 # Formato nativo de OpenCV
        '-s', f'{ANCHO}x{ALTO}', '-r', str(FPS),
        '-i', '-',                           # Recibe los fotogramas por la tubería (stdin)
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
        '-pix_fmt', 'yuv420p',               # CORRECCIÓN: Fuerza formato estándar compatible con RTSP
        '-rtsp_transport', 'tcp',            # CORRECCIÓN: Fuerza canal seguro TCP para evitar el Bad Request
        '-an',                               # Desactivado el audio de entrada local por ahora
        '-f', 'rtsp', RTSP_URL               # Inyección directa en MediaMTX
    ]
    try:
        proceso_stream = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)
        print("-> [OK] Codificador listo y conectado a MediaMTX.")
    except Exception as e:
        print(f"Error al iniciar FFmpeg (¿Está MediaMTX corriendo?): {e}")
        return

    # 4. Inicialización de Picamera2
    print("Iniciando Raspberry Pi Camera Module v2...")
    try:
        picam2 = Picamera2()
        picam2.configure(picam2.create_video_configuration(
            main={"format": "RGB888", "size": (ANCHO, ALTO)}
        ))
        picam2.start()
        print("-> [OK] Cámara v2 lista mediante Picamera2.")
    except Exception as cam_error:
        print(f"Error: No se pudo inicializar la cámara. {cam_error}")
        if proceso_stream:
            proceso_stream.stdin.close()
            proceso_stream.wait()
        return

    # 5. Activar la Escucha de Audio en Tiempo Real (Segundo Plano)
    print("📡 [SISTEMA] Activando canal receptor de Walkie-Talkie...")
    coleccion_audio_ref = db.collection("comandos_audio")
    observador = coleccion_audio_ref.on_snapshot(reproducir_audio)

    print("\n==================================================")
    print(" 🤖 [PETWATCH] ¡SISTEMA OPERATIVO Y CONECTADO! ")
    print("--> Transmitiendo vídeo a la IA y escuchando amplificador I2S.")
    print("--> Para apagar de forma segura, pulsa Ctrl + C.")
    print("==================================================\n")

    ultimo_envio_ia = 0.0

    try:
        while True:
            frame_rgb = picam2.capture_array("main")
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            try:
                # Enviar los píxeles puros a FFmpeg para el streaming en directo
                proceso_stream.stdin.write(frame_bgr.tobytes())
            except Exception as stream_error:
                # Ya no saldrá el molesto bucle infinito si FFmpeg está bien configurado
                print(f"Error en el stream en directo: {stream_error}")

            # Enviar fotogramas comprimidos a la IA cada 0.2 segundos
            tiempo_actual = time.time()
            if tiempo_actual - ultimo_envio_ia >= 0.2:
                _, buffer = cv2.imencode('.jpg', frame_bgr)
                img_bytes = buffer.tobytes()

                try:
                    future = publisher.publish(topic_path, img_bytes)
                    print(f"\r[VÍDEO] Transmitiendo fotograma activo... ID: {future.result()[:15]}...", end="", flush=True)
                    ultimo_envio_ia = tiempo_actual
                except Exception as pub_error:
                    print(f"\nError al enviar a Pub/Sub: {pub_error}")

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n\n🛑 [SISTEMA] Solicitud de apagado manual detectada.")
    finally:
        print("Cerrando recursos del robot de manera segura...")
        picam2.stop()
        if proceso_stream:
            proceso_stream.stdin.close()
            proceso_stream.wait()
        print("¡Cámara y hilos multimedia cerrados correctamente. Robot en reposo!")


if __name__ == "__main__":
    main()