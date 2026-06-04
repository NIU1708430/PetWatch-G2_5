import base64
import time
import os
import subprocess
from google.cloud import firestore

# Conectamos a tu base de datos específica
db = firestore.Client(project="petwatch-sm", database="petwatch-db")

def reproducir_audio(documentos_totales, cambios, hora_lectura):
    """Se ejecuta AUTOMÁTICAMENTE cada vez que entra un audio nuevo en Firestore"""
    
    for cambio in cambios:
        # Solo nos interesan los documentos que se acaban de AÑADIR
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            
            # Si el audio no ha sido reproducido todavía
            if datos.get('reproducido') is False:
                print("🎤 ¡Entrando audio desde la web PetWatch!")
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
                        # --- CONVERSIÓN CON FFMPEG ---
                        # Forzamos 44100 Hz (frecuencia universal que aceptan el 100% de los altavoces)
                        subprocess.run([
                            'ffmpeg', '-i', archivo_entrada, 
                            '-acodec', 'pcm_s16le', '-ar', '44100', 
                            archivo_salida, '-y', '-loglevel', 'quiet'
                        ], check=True)
                        
                        # --- REPRODUCCIÓN DIRECTA AL AMPLIFICADOR I2S (TARJETA 2) ---
                        print("🔊 Enviando audio directo a los pines del amplificador (Tarjeta 2)...")
                        subprocess.run(['aplay', '-D', 'plughw:2,0', archivo_salida], check=True)
                        print("✅ Mensaje emitido por el altavoz.")
                        
                    except subprocess.CalledProcessError:
                        print("❌ Error: FFMPEG o APLAY han fallado en el proceso.")
                    except Exception as audio_error:
                        print(f"❌ Error al reproducir en el altavoz: {audio_error}")
                    finally:
                        # Limpieza estricta de archivos temporales
                        if os.path.exists(archivo_entrada): os.remove(archivo_entrada)
                        if os.path.exists(archivo_salida): os.remove(archivo_salida)

                # Marcamos el audio como REPRODUCIDO en Firestore para evitar bucles
                cambio.document.reference.update({'reproducido': True})
                print("📌 Documento marcado como leído en la base de datos.\n")

# Ponemos a Firestore en modo "escucha activa en tiempo real"
print("📡 Robot escuchando el canal de audio de PetWatch... Habla desde la web.")
coleccion_audio_ref = db.collection("comandos_audio")
observador = coleccion_audio_ref.on_snapshot(reproducir_audio)

# Mantener el script corriendo para siempre
while True:
    time.sleep(1)