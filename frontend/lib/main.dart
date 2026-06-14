import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'firebase_options.dart';
import 'package:record/record.dart';
import 'package:http/http.dart' as http;

void main() async {
  // Asegura que los bindings de la plataforma esten listos antes de inicializar Firebase
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );

  FirebaseMessaging messaging = FirebaseMessaging.instance;

  // Solicitud explicita de permisos en iOS/Android para poder recibir las alertas infraganti
  NotificationSettings settings = await messaging.requestPermission(
    alert: true,
    badge: true,
    sound: true,
  );

  if (settings.authorizationStatus == AuthorizationStatus.authorized) {
    print('Permiso concedido por el usuario.');

    try {
      // Obtenemos el identificador unico de este dispositivo.
      // Se utiliza la VAPID key para la compatibilidad web/cross-platform.
      String? token = await messaging.getToken(
        vapidKey: "BHJbHkXwhqyhTj1c_XukOibvLlR_EEKk6tssz8uxI5Qy0ZQHjga62JwqVQHOuQdRRQ_MaTYbFZ7PeAaOiYnflmw",
      );
      
      if (token != null) {
        // Persistimos el token en Firestore. La Cloud Function leera esta coleccion 
        // para hacer el envio Multicast (Push) a todos los clientes activos.
        await FirebaseFirestore.instanceFor(app: Firebase.app(), databaseId: 'petwatch-db')
            .collection('usuarios_suscritos')
            .doc(token)
            .set({
              'token': token,
              'fecha_registro': FieldValue.serverTimestamp(),
            });
        print("Token registrado correctamente en la base de datos.");
      }
    } catch (e) {
      print("Fallo critico al solicitar el token FCM: $e");
    }
  } else {
    print('Permisos de notificacion rechazados por el SO o el usuario.');
  }

  runApp(const PetWatchApp());
}

class PetWatchApp extends StatelessWidget {
  const PetWatchApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'PetWatch Live',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.red, brightness: Brightness.dark),
        useMaterial3: true,
      ),
      home: const MainNavigationScreen(),
    );
  }
}

class MainNavigationScreen extends StatefulWidget {
  const MainNavigationScreen({super.key});

  @override
  State<MainNavigationScreen> createState() => _MainNavigationScreenState();
}

class _MainNavigationScreenState extends State<MainNavigationScreen> {
  // Gestor de estado simple para la navegacion inferior
  int _pestanaActual = 0;

  final List<Widget> _pantallas = [
    const LiveViewerBody(),
    const AlertsGalleryBody(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        title: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // Indicador visual de estado
            Icon(Icons.circle, color: _pestanaActual == 0 ? Colors.red : Colors.green, size: 12),
            const SizedBox(width: 8),
            Text(
              _pestanaActual == 0 ? 'PETWATCH LIVE' : 'GALERÍA INFRAGANTI',
              style: const TextStyle(fontWeight: FontWeight.bold, letterSpacing: 1.2),
            ),
          ],
        ),
        backgroundColor: Colors.black87,
        centerTitle: true,
      ),
      body: _pantallas[_pestanaActual],
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _pestanaActual,
        onTap: (indice) {
          setState(() {
            _pestanaActual = indice;
          });
        },
        backgroundColor: Colors.grey[950],
        selectedItemColor: Colors.redAccent,
        unselectedItemColor: Colors.white54,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.videocam), label: 'En Directo'),
          BottomNavigationBarItem(icon: Icon(Icons.photo_library), label: 'Historial Alertas'),
        ],
      ),
    );
  }
}

class LiveViewerBody extends StatefulWidget {
  const LiveViewerBody({super.key});

  @override
  State<LiveViewerBody> createState() => _LiveViewerBodyState();
}

class _LiveViewerBodyState extends State<LiveViewerBody> {
  final AudioRecorder _grabadorAudio = AudioRecorder();
  
  // Variables de bloqueo de estado de la UI para evitar pulsaciones multiples (Debounce)
  bool _grabando = false;
  bool _botonPulsado = false;
  bool _dispensando = false;

  void _dispensarPremioManual() async {
    // Bloqueamos el boton en la interfaz temporalmente
    setState(() {
      _dispensando = true;
    });

    try {
      // Inyectamos el evento asincrono en Firestore.
      // El campo 'completado: false' es vital para la idempotencia en el robot.
      await FirebaseFirestore.instanceFor(app: Firebase.app(), databaseId: 'petwatch-db')
          .collection('comandos_servo')
          .add({
        'accion': 'dispensar',
        'fecha_hora': FieldValue.serverTimestamp(),
        'completado': false,
      });
      
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('¡Premio enviado al robot! 🦴', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
            backgroundColor: Colors.orange,
            duration: Duration(seconds: 2),
          ),
        );
      }
    } catch (e) {
      print("Error en I/O al intentar escribir en comandos_servo: $e");
    }

    // Simulamos un cooldown visual antes de volver a habilitar el boton
    await Future.delayed(const Duration(seconds: 3));
    if (mounted) {
      setState(() {
        _dispensando = false;
      });
    }
  }

  void _iniciarGrabacion() async {
    setState(() {
      _botonPulsado = true;
    });

    try {
      if (await _grabadorAudio.hasPermission()) {
        if (!_botonPulsado) return;

        // Se usa Opus a 16kHz para maximizar la relacion calidad/compresion 
        // ya que este archivo viajara incrustado como texto (Base64) en Firestore
        await _grabadorAudio.start(
          const RecordConfig(encoder: AudioEncoder.opus, sampleRate: 16000),
          path: '',
        );
        setState(() { _grabando = true; });
        
        // Manejo de edge case: el usuario solto el boton antes de que la inicializacion terminara
        if (!_botonPulsado) _detenerYEnviarGrabacion();
      } else {
        setState(() { _botonPulsado = false; });
      }
    } catch (e) {
      setState(() { _botonPulsado = false; });
    }
  }

  void _detenerYEnviarGrabacion() async {
    setState(() { _botonPulsado = false; });
    if (!_grabando) return;

    try {
      final rutaBlob = await _grabadorAudio.stop();
      setState(() { _grabando = false; });

      if (rutaBlob != null) {
        // Peticion HTTP local para recuperar el blob desde la memoria volatil del dispositivo
        final respuesta = await http.get(Uri.parse(rutaBlob));
        final bytesAudio = respuesta.bodyBytes;
        
        // Serializacion a Base64 para poder inyectarlo en un documento NoSQL
        String audioBase64 = base64Encode(bytesAudio);

        await FirebaseFirestore.instanceFor(app: Firebase.app(), databaseId: 'petwatch-db')
            .collection('comandos_audio')
            .add({
              'audio_b64': audioBase64,
              'fecha_hora': FieldValue.serverTimestamp(),
              'reproducido': false, // El robot pondra esto a True cuando el I2S lo consuma
            });
      }
    } catch (e) {
      print("Error durante el encoding o la subida del buffer de audio: $e");
    }
  }

  @override
  void dispose() {
    _grabadorAudio.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // El StreamBuilder suscribe la interfaz directamente a la base de datos (Observer Pattern).
    // Cada vez que la IA en Cloud procesa un fotograma, la pantalla se refresca automaticamente.
    return StreamBuilder<QuerySnapshot>(
      stream: FirebaseFirestore.instanceFor(app: Firebase.app(), databaseId: 'petwatch-db')
          .collection('historial_mascotas')
          .orderBy('fecha_hora', descending: true)
          .limit(1)
          .snapshots(),
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator(color: Colors.red));
        }

        if (!snapshot.hasData || snapshot.data!.docs.isEmpty) {
          return const Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.videocam_off, color: Colors.white38, size: 64),
                SizedBox(height: 16),
                Text('Esperando señal de telemetría...', style: TextStyle(color: Colors.white54, fontSize: 16)),
              ],
            ),
          );
        }

        var datosUltimaCaptura = snapshot.data!.docs.first.data() as Map<String, dynamic>;
        String? fotoBase64 = datosUltimaCaptura['foto_b64'];
        String animal = datosUltimaCaptura['animal'] ?? 'Desconocido';
        String postura = datosUltimaCaptura['postura'] ?? 'Procesando...';

        return Column(
          children: [
            // Frame Viewer: Deserializa en tiempo real el Base64 a pixeles
            Expanded(
              child: Container(
                color: Colors.grey[950],
                alignment: Alignment.center,
                child: fotoBase64 != null
                    // gaplessPlayback es crucial para evitar el parpadeo negro entre frames asincronos
                    ? Image.memory(base64Decode(fotoBase64), fit: BoxFit.contain, gaplessPlayback: true)
                    : const Center(child: Text('Frame droppeado o vacio', style: TextStyle(color: Colors.white54))),
              ),
            ),
            
            // Consola de Actuadores IoT
            Padding(
              padding: const EdgeInsets.only(top: 16, bottom: 8),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  Column(
                    children: [
                      Listener(
                        behavior: HitTestBehavior.opaque,
                        onPointerDown: (_) => _iniciarGrabacion(),
                        onPointerUp: (_) => _detenerYEnviarGrabacion(),
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 70),
                          width: 70,  
                          height: 70,
                          decoration: BoxDecoration(
                            color: _botonPulsado ? Colors.green : Colors.red,
                            shape: BoxShape.circle,
                            boxShadow: [
                              BoxShadow(
                                color: (_botonPulsado ? Colors.green : Colors.red).withOpacity(0.4),
                                blurRadius: 15,
                                spreadRadius: _botonPulsado ? 6 : 2
                              )
                            ],
                          ),
                          child: const Center(
                            child: Icon(Icons.mic, color: Colors.white, size: 36),
                          ),
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        _botonPulsado ? "Transmitiendo al Edge..." : "Mantén para hablar",
                        style: TextStyle(color: _botonPulsado ? Colors.green : Colors.white54, fontSize: 12, fontWeight: FontWeight.bold),
                      ),
                    ],
                  ),

                  Column(
                    children: [
                      GestureDetector(
                        onTap: _dispensando ? null : _dispensarPremioManual,
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 200),
                          width: 70,  
                          height: 70,
                          decoration: BoxDecoration(
                            color: _dispensando ? Colors.grey[700] : Colors.orange,
                            shape: BoxShape.circle,
                            boxShadow: [
                              BoxShadow(
                                color: (_dispensando ? Colors.transparent : Colors.orange).withOpacity(0.4),
                                blurRadius: 15,
                                spreadRadius: _dispensando ? 1 : 2
                              )
                            ],
                          ),
                          child: Center(
                            child: _dispensando
                              ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                              : const Icon(Icons.pets, color: Colors.white, size: 36),
                          ),
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        _dispensando ? "Cooldown hardware" : "Activar Servo",
                        style: TextStyle(color: _dispensando ? Colors.white38 : Colors.white54, fontSize: 12, fontWeight: FontWeight.bold),
                      ),
                    ],
                  ),
                ],
              ),
            ),

            // Metadatos Cognitivos
            Container(
              padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 32),
              color: Colors.black87,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  Column(
                    children: [
                      const Text('ENTIDAD DETECTADA', style: TextStyle(color: Colors.white38, fontSize: 12, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 4),
                      Text(animal.toUpperCase(), style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold)),
                    ],
                  ),
                  Container(width: 1, height: 40, color: Colors.white12),
                  Column(
                    children: [
                      const Text('CLASIFICACIÓN POSTURAL', style: TextStyle(color: Colors.white38, fontSize: 12, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 4),
                      Text(postura.toUpperCase(), style: const TextStyle(color: Colors.redAccent, fontSize: 20, fontWeight: FontWeight.bold)),
                    ],
                  ),
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}

class AlertsGalleryBody extends StatelessWidget {
  const AlertsGalleryBody({super.key});

  @override
  Widget build(BuildContext context) {
    // Al igual que el visor, esta consulta persiste abierta pero contra 
    // la coleccion de alertes infraganti, generando la galeria reactiva.
    return StreamBuilder<QuerySnapshot>(
      stream: FirebaseFirestore.instanceFor(app: Firebase.app(), databaseId: 'petwatch-db')
          .collection('alertas_guardadas')
          .orderBy('fecha_hora', descending: true)
          .snapshots(),
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator(color: Colors.green));
        }

        if (!snapshot.hasData || snapshot.data!.docs.isEmpty) {
          return const Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.photo_library_outlined, color: Colors.white38, size: 64),
                SizedBox(height: 16),
                Text('Buffer de historial vacío.', style: TextStyle(color: Colors.white54, fontSize: 16)),
              ],
            ),
          );
        }

        return GridView.builder(
          padding: const EdgeInsets.all(12),
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 2,
            crossAxisSpacing: 12,
            mainAxisSpacing: 12,
            childAspectRatio: 0.8,
          ),
          itemCount: snapshot.data!.docs.length,
          itemBuilder: (context, index) {
            var alerta = snapshot.data!.docs[index].data() as Map<String, dynamic>;
            String? fotoB64 = alerta['foto_b64'];
            String animal = alerta['animal'] ?? 'Mascota';
            String postura = alerta['postura'] ?? 'Acción';
            
            var fechaRaw = alerta['fecha_hora'];
            String horaTexto = "Syncing...";
            
            if (fechaRaw != null && fechaRaw is Timestamp) {
              DateTime dt = fechaRaw.toDate();
              horaTexto = "${dt.day}/${dt.month} - ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}";
            }

            return Card(
              color: Colors.grey[900],
              clipBehavior: Clip.antiAlias,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(
                    child: fotoB64 != null
                        ? Image.memory(base64Decode(fotoB64), fit: BoxFit.cover)
                        : Container(color: Colors.grey[800], child: const Icon(Icons.broken_image)),
                  ),
                  Padding(
                    padding: const EdgeInsets.all(8.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(horaTexto, style: const TextStyle(color: Colors.white54, fontSize: 11)),
                        const SizedBox(height: 2),
                        Text(
                          "${animal.toUpperCase()} - $postura",
                          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }
}