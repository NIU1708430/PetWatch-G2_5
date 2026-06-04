import base64
import time
import os
import subprocess
import cv2
from google.cloud import pubsub_v1
from google.cloud import firestore
import pygame
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


def reproducir_audio(cambios_docs, objeto_contexto, hora_lectura):
    """
    Se ejecuta AUTOMÁTICAMENTE en segundo plano (gracias al Snapshot de Firestore)
    cada vez que entra un audio nuevo desde la aplicación web de Flutter.
    """
    for cambio in cambios_docs:
        # Solo nos interesan los documentos que se acaban de AÑADIR
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            
            # Si el audio no ha sido reproducido todavía
            if datos.get('reproducido') is False:
                print("\n🎤 [ALTAVOZ] ¡Entrando audio desde la web PetWatch!")
                audio_b64 = datos.get('audio_b64')
                
                if audio_b64:
                    # Definimos los nombres de los archivos temporales
                    archivo_entrada = "mensaje_web.webm"
                    archivo_salida = "mensaje_robot.wav"
                    
                    # Decodificamos el Base64 tal y como viene de la web
                    bytes_audio = base64.b64decode(audio_b64)
                    with open(archivo_entrada, "wb") as archivo_webm:
                        archivo_webm.write(bytes_audio)
                    
                    try:
                        # --- CONVERSIÓN CON FFMPEG EN SEGUNDO PLANO ---
                        # Transforma el contenedor WebM/Opus de Chrome en un WAV Estándar (PCM 16-bit)
                        subprocess.run([
                            'ffmpeg', '-i', archivo_entrada, 
                            '-acodec', 'pcm_s16le', '-ar', '16000', 
                            archivo_salida, '-y', '-loglevel', 'quiet'
                        ], check=True)
                        
                        # Reproducir el sonido limpio por los altavoces físicos
                        pygame.mixer.music.load(archivo_salida)
                        pygame.mixer.music.play()
                        while pygame.mixer.music.get_busy():
                            time.sleep(0.1) # Esperamos en su propio hilo a que termine de hablar
                        pygame.mixer.music.unload()
                        print("✅ [ALTAVOZ] Mensaje emitido correctamente por el hardware.")
                        
                    except subprocess.CalledProcessError:
                        print("❌ [ALTAVOZ] Error: FFMPEG falló al convertir el formato del audio.")
                    except Exception as audio_error:
                        print(f"❌ [ALTAVOZ] Error al reproducir en el altavoz: {audio_error}")
                    finally:
                        # Limpieza estricta de archivos temporales
                        if os.path.exists(archivo_entrada): os.remove(archivo_entrada)
                        if os.path.exists(archivo_salida): os.remove(archivo_salida)

                # Marcamos el audio como REPRODUCIDO en Firestore para evitar bucles de lectura
                cambio.document.reference.update({'reproducido': True})
                print("📌 [DATABASE] Documento marcado como leído en Firestore.\n")


def main():
    print("==================================================")
    print("       PETWATCH CLOUD - SISTEMA INTEGRADO         ")
    print("==================================================")

    # 1. Inicialización de Pygame Mixer (Audio local)
    pygame.mixer.init()

    # 2. Conexión con Google Cloud Pub/Sub
    print("Conectando con Google Cloud Pub/Sub...")
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
        print("-> [OK] Conexión Pub/Sub establecida.")
    except Exception as e:
        print(f"Error al conectar con Pub/Sub: {e}")
        return

    # 3. Conexión con Google Cloud Firestore
    print("Conectando con Google Cloud Firestore...")
    try:
        db = firestore.Client(project=PROJECT_ID, database=DATABASE_ID)
        print("-> [OK] Conexión Firestore establecida.")
    except Exception as e:
        print(f"Error al conectar con Firestore: {e}")
        return

    # 4. Configurar FFmpeg Subprocess para el Vídeo en Directo (Hacia MediaMTX)
    print("Iniciando codificador multimedia (Tubería de vídeo)...")
    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24',                 # Formato nativo de OpenCV
        '-s', f'{ANCHO}x{ALTO}', '-r', str(FPS),
        '-i', '-',                           # Recibe los fotogramas por la tubería (stdin)
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
        '-an',                               # Desactivado el audio del micro de entrada por ahora
        '-f', 'rtsp', RTSP_URL               # Inyección directa en MediaMTX
    ]
    try:
        proceso_stream = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)
        print("-> [OK] Codificador listo y conectado a MediaMTX.")
    except Exception as e:
        print(f"Error al iniciar FFmpeg (¿Está MediaMTX corriendo?): {e}")
        return

    # 5. Inicialización de Picamera2
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

    # 6. Activar la Escucha de Audio en Tiempo Real (Segundo Plano)
    print("📡 [SISTEMA] Activando canal receptor de Walkie-Talkie...")
    coleccion_audio_ref = db.collection("comandos_audio")
    # on_snapshot lanza automáticamente un hilo nativo en background. No bloquea el main()
    observador = coleccion_audio_ref.on_snapshot(reproducir_audio)

    print("\n==================================================")
    print(" 🤖 [PETWATCH] ¡SISTEMA OPERATIVO Y CONECTADO! ")
    print("--> Transmitiendo vídeo a la IA y escuchando altavoz.")
    print("--> Para apagar de forma segura, pulsa Ctrl + C.")
    print("==================================================\n")

    ultimo_envio_ia = 0.0

    try:
        while True:
            # Capturar un fotograma directamente en memoria (Matriz RGB)
            frame_rgb = picam2.capture_array("main")

            # Convertir la matriz de RGB a BGR (Lo que entiende OpenCV y nuestro FFmpeg de vídeo)
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            try:
                # Enviar los píxeles puros a FFmpeg para el streaming en directo
                proceso_stream.stdin.write(frame_bgr.tobytes())
            except Exception as stream_error:
                print(f"Error en el stream en directo: {stream_error}")

            # Enviar fotogramas comprimidos a la IA cada 0.2 segundos
            tiempo_actual = time.time()
            if tiempo_actual - ultimo_envio_ia >= 0.2:
                _, buffer = cv2.imencode('.jpg', frame_bgr)
                img_bytes = buffer.tobytes()

                try:
                    future = publisher.publish(topic_path, img_bytes)
                    # Imprime en la misma línea usando '\r' para no inundar la pantalla de logs
                    print(f"\r[VÍDEO] Transmitiendo fotograma activo... ID: {future.result()[:15]}...", end="", flush=True)
                    ultimo_envio_ia = tiempo_actual
                except Exception as pub_error:
                    print(f"\nError al enviar a Pub/Sub: {pub_error}")

            # Sincronización básica del bucle multimedia
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