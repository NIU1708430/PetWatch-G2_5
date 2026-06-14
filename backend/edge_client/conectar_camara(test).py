import time
import cv2  
import subprocess
from google.cloud import pubsub_v1
from picamera2 import Picamera2

# Credenciales y parametros de streaming local/nube
PROJECT_ID = "petwatch-sm"
TOPIC_ID = "petwatch-video-stream"
RTSP_URL = "rtsp://localhost:8554/mascota"
ANCHO = 640
ALTO = 480
FPS = 25

def main():
    print("Iniciando modulo de transmision dual (Pub/Sub + RTSP)...")

    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
    except Exception as e:
        print(f"Fallo de conexion con Pub/Sub: {e}")
        return

    # Invocamos a FFmpeg mediante un subproceso para multiplexar el video crudo y enviarlo a MediaMTX.
    # El preset 'ultrafast' y 'zerolatency' minimizan el retardo en la red local.
    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24',                 
        '-s', f'{ANCHO}x{ALTO}', '-r', str(FPS),
        '-i', '-',                           
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
        '-an', # Deshabilita el audio temporalmente hasta configurar ALSA
        '-f', 'rtsp', RTSP_URL               
    ]
    
    try:
        proceso_stream = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)
    except Exception as e:
        print(f"Error al levantar FFmpeg. Verifica el servicio MediaMTX: {e}")
        return

    try:
        picam2 = Picamera2()
        picam2.configure(picam2.create_video_configuration(
            main={"format": "RGB888", "size": (ANCHO, ALTO)}
        ))
        picam2.start()
    except Exception as cam_error:
        print(f"Error de hardware en la camara: {cam_error}")
        return

    print("Transmision dual activa. Presiona Ctrl+C para finalizar.")
    ultimo_envio_ia = 0.0

    try:
        while True:
            # Lectura directa a RAM para evitar cuellos de botella de I/O en la tarjeta SD
            frame_rgb = picam2.capture_array("main")
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            try:
                # Inyeccion del frame crudo en la tuberia estandar (stdin) hacia FFmpeg
                proceso_stream.stdin.write(frame_bgr.tobytes())
            except Exception as stream_error:
                print(f"Caida del buffer RTSP: {stream_error}")

            tiempo_actual = time.time()
            if tiempo_actual - ultimo_envio_ia >= 0.2:
                # Compresion en tiempo de ejecucion para no exceder los limites de payload de Pub/Sub
                _, buffer = cv2.imencode('.jpg', frame_bgr)
                img_bytes = buffer.tobytes()

                try:
                    future = publisher.publish(topic_path, img_bytes)
                    print(f"[{time.strftime('%H:%M:%S')}] Payload subido. ID: {future.result()}")
                    ultimo_envio_ia = tiempo_actual
                except Exception as pub_error:
                    print(f"Error de subida a la nube: {pub_error}")

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nInterrupcion manual detectada.")
    finally:
        picam2.stop()
        if proceso_stream:
            proceso_stream.stdin.close()
            proceso_stream.wait()
        print("Procesos terminados de forma segura.")

if __name__ == "__main__":
    main()