import base64
import time
import os
import subprocess
from google.cloud import firestore

# Inicializacion del cliente de base de datos
db = firestore.Client(project="petwatch-sm", database="petwatch-db")

def reproducir_audio(documentos_totales, cambios, hora_lectura):
    # Callback asincrono para manejar la cola de mensajes de voz
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            
            # Garantiza la idempotencia: evita que un fallo de red reproduzca el mismo audio dos veces
            if datos.get('reproducido') is False:
                print("Procesando nuevo paquete de audio entrante...")
                audio_b64 = datos.get('audio_b64')
                
                if audio_b64:
                    archivo_entrada = "mensaje_web.webm"
                    archivo_salida = "mensaje_robot.wav"
                    
                    bytes_audio = base64.b64decode(audio_b64)
                    with open(archivo_entrada, "wb") as archivo_webm:
                        archivo_webm.write(bytes_audio)
                    
                    try:
                        # Transcodificacion forzada a WAV PCM_s16le 44.1kHz para garantizar soporte en drivers ALSA
                        subprocess.run([
                            'ffmpeg', '-i', archivo_entrada, 
                            '-acodec', 'pcm_s16le', '-ar', '44100', 
                            archivo_salida, '-y', '-loglevel', 'quiet'
                        ], check=True)
                        
                        # Enrutamiento directo del audio al bus I2S (Hardware card 2)
                        subprocess.run(['aplay', '-D', 'plughw:2,0', archivo_salida], check=True)
                        print("Audio reproducido con exito a traves del I2S.")
                        
                    except subprocess.CalledProcessError:
                        print("Fallo en la tuberia de decodificacion de FFmpeg o aplay.")
                    except Exception as audio_error:
                        print(f"Excepcion de hardware de audio: {audio_error}")
                    finally:
                        # Control de recoleccion de basura manual para evitar fugas de memoria en la SD
                        if os.path.exists(archivo_entrada): os.remove(archivo_entrada)
                        if os.path.exists(archivo_salida): os.remove(archivo_salida)

                cambio.document.reference.update({'reproducido': True})

print("Instanciando listener asincrono de Firestore para el canal 'comandos_audio'...")
coleccion_audio_ref = db.collection("comandos_audio")
observador = coleccion_audio_ref.on_snapshot(reproducir_audio)

# Bloqueo del hilo principal para mantener vivo el listener
while True:
    time.sleep(1)