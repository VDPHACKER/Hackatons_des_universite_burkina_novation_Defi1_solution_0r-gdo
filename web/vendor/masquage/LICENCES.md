# Composants de masquage des visages et des plaques (tous exécutés dans le navigateur, hors ligne)

| Fichier | Origine | Licence |
|---|---|---|
| `mediapipe/` | `@mediapipe/tasks-vision` (npm), Google | Apache-2.0 |
| `modeles/blaze_face_short_range.tflite` | Google MediaPipe, détecteur de visages BlazeFace | Apache-2.0 |
| `ort/` | `onnxruntime-web` (npm), Microsoft | MIT |
| `modeles/yolo-v9-t-384-license-plates-end2end.onnx` | github.com/ankandrew/open-image-models (release « assets ») | MIT |

Les images ne quittent jamais le téléphone avant le masquage.
| `modeles/efficientdet_lite0.tflite` | Google MediaPipe, détecteur d'objets EfficientDet-Lite0 (COCO), utilisé pour trouver les personnes lointaines | Apache-2.0 |
