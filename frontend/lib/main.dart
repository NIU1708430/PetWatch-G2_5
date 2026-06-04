import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'firebase_options.dart';
import 'package:record/record.dart';
import 'package:http/http.dart' as http;

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );

  FirebaseMessaging messaging = FirebaseMessaging.instance;

  NotificationSettings settings = await messaging.requestPermission(
    alert: true,
    badge: true,
    sound: true,
  );

  if (settings.authorizationStatus == AuthorizationStatus.authorized) {
    print('¡Permiso concedido por el usuario!');

    try {
      String? token = await messaging.getToken(
        vapidKey: "BHJbHkXwhqyhTj1c_XukOibvLlR_EEKk6tssz8uxI5Qy0ZQHjga62JwqVQHOuQdRRQ_MaTYbFZ7PeAaOiYnflmw", 
      );
      
      if (token != null) {
        print("================ TOKEN DEL MÓVIL ================");
        print(token);
        
        await FirebaseFirestore.instanceFor(app: Firebase.app(), databaseId: 'petwatch-db')
            .collection('usuarios_suscritos')
            .doc(token)
            .set({
              'token': token,
              'fecha_registro': FieldValue.serverTimestamp(),
            });
        print("✅ Token guardado CORRECTAMENTE en petwatch-db.");
      }
    } catch (e) {
      print("❌ ERROR REAL AL PEDIR EL TOKEN:");
      print(e.toString());
    }
  } else {
    print('El usuario rechazó los permisos de notificación.');
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

// --- PANTALLA PRINCIPAL CON NAVEGACIÓN ---
class MainNavigationScreen extends StatefulWidget {
  const MainNavigationScreen({super.key});

  @override
  State<MainNavigationScreen> createState() => _MainNavigationScreenState();
}

class _MainNavigationScreenState extends State<MainNavigationScreen> {
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

// --- PESTAÑA 1: EL VÍDEO EN DIRECTO CON WALKIE-TALKIE ---
class LiveViewerBody extends StatefulWidget {
  const LiveViewerBody({super.key});

  @override
  State<LiveViewerBody> createState() => _LiveViewerBodyState();
}

class _LiveViewerBodyState extends State<LiveViewerBody> {
  final AudioRecorder _grabadorAudio = AudioRecorder();
  bool _grabando = false;
  bool _botonPulsado = false; // Control de pulsación física

  // Función para empezar a grabar al pulsar
  void _iniciarGrabacion() async {
    print("🎯 Botón presionado (Intentando iniciar...)");
    
    // CORRECCIÓN: setState inmediato para cambiar a VERDE al milisegundo
    setState(() {
      _botonPulsado = true;
    });

    try {
      if (await _grabadorAudio.hasPermission()) {
        print("🔓 Permiso de micrófono confirmado.");
        
        // Si el usuario soltó el botón antes de que el hardware responda, cancelamos
        if (!_botonPulsado) return;

        await _grabadorAudio.start(
          const RecordConfig(encoder: AudioEncoder.opus, sampleRate: 16000), 
          path: '',
        );
        
        setState(() {
          _grabando = true;
        });
        print("🎤 Grabando audio con éxito...");

        // Si soltó el botón justo mientras se encendía el micro, forzamos el envío inmediato
        if (!_botonPulsado) {
          print("⏱️ Envío síncrono retrasado activado.");
          _detenerYEnviarGrabacion();
        }
      } else {
        print("❌ El usuario no dio permiso para usar el micrófono.");
        setState(() {
          _botonPulsado = false;
        });
      }
    } catch (e) {
      print("❌ Error crítico al iniciar grabación: $e");
      setState(() {
        _botonPulsado = false;
      });
    }
  }

  // Función para detener y subir a Firestore al soltar
  void _detenerYEnviarGrabacion() async {
    print("🎯 Botón soltado (Intentando procesar audio...)");
    
    // CORRECCIÓN: setState inmediato para volver a ROJO al instante
    setState(() {
      _botonPulsado = false;
    });

    if (!_grabando) {
      print("⏳ Esperando a que el hardware se inicialice por completo...");
      return;
    }

    try {
      final rutaBlob = await _grabadorAudio.stop();
      setState(() {
        _grabando = false;
      });

      if (rutaBlob != null) {
        print("💾 Audio capturado en el navegador: $rutaBlob");
        
        final respuesta = await http.get(Uri.parse(rutaBlob));
        final bytesAudio = respuesta.bodyBytes;

        String audioBase64 = base64Encode(bytesAudio);

        await FirebaseFirestore.instanceFor(app: Firebase.app(), databaseId: 'petwatch-db')
            .collection('comandos_audio')
            .add({
              'audio_b64': audioBase64,
              'fecha_hora': FieldValue.serverTimestamp(),
              'reproducido': false,
            });
        
        print("🚀 ¡Audio enviado a Firestore con éxito!");
      }
    } catch (e) {
      print("❌ Error al detener o subir audio: $e");
    }
  }

  @override
  void dispose() {
    _grabadorAudio.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
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
                Text('Esperando señal del robot...', style: TextStyle(color: Colors.white54, fontSize: 16)),
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
            Expanded(
              child: Container(
                color: Colors.grey[950],
                alignment: Alignment.center,
                child: fotoBase64 != null
                    ? Image.memory(base64Decode(fotoBase64), fit: BoxFit.contain, gaplessPlayback: true)
                    : const Center(child: Text('Captura recibida sin imagen', style: TextStyle(color: Colors.white54))),
              ),
            ),
            
            // --- BOTÓN WALKIE-TALKIE CON RESPUESTA DE COLOR INSTANTÁNEA ---
            Padding(
              padding: const EdgeInsets.only(top: 16),
              child: Listener(
                behavior: HitTestBehavior.opaque, 
                onPointerDown: (_) => _iniciarGrabacion(),
                onPointerUp: (_) => _detenerYEnviarGrabacion(),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 70), // Transición ultra rápida
                  width: 70,  
                  height: 70, 
                  decoration: BoxDecoration(
                    // MODIFICADO: Color e iluminación reactivos al dedo (_botonPulsado)
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
                    child: Icon(
                      Icons.mic, 
                      color: Colors.white, 
                      size: 36 
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 6),
            Text(
              // MODIFICADO: Texto reactivo al dedo para sincronía perfecta
              _botonPulsado ? "¡HABLANDO EN VIVO!" : "Mantén pulsado para hablar",
              style: TextStyle(color: _botonPulsado ? Colors.green : Colors.white54, fontSize: 12, fontWeight: FontWeight.bold),
            ),

            Container(
              padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 32),
              color: Colors.black87,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  Column(
                    children: [
                      const Text('DETECTADO', style: TextStyle(color: Colors.white38, fontSize: 12, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 4),
                      Text(animal.toUpperCase(), style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold)),
                    ],
                  ),
                  Container(width: 1, height: 40, color: Colors.white12),
                  Column(
                    children: [
                      const Text('POSTURA / ACCIÓN', style: TextStyle(color: Colors.white38, fontSize: 12, fontWeight: FontWeight.bold)),
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

// --- PESTAÑA 2: GALERÍA DE FOTOS PERMANENTES ---
class AlertsGalleryBody extends StatelessWidget {
  const AlertsGalleryBody({super.key});

  @override
  Widget build(BuildContext context) {
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
                Text('Aún no hay alertas guardadas en el historial.', style: TextStyle(color: Colors.white54, fontSize: 16)),
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
            String horaTexto = "Reciente";
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
                        : Container(color: Colors.grey[800], child: const Icon(Icons.image_not_supported)),
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