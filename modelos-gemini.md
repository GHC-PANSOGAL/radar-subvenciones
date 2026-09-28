# Modelos de Gemini disponibles para nuestra clave

44 modelos admiten generateContent:

```
models/antigravity-preview-05-2026            Antigravity Agent Preview
models/antigravity-preview-09-2026            Antigravity Agent Preview
models/antigravity-preview-latest             Antigravity Agent Preview Latest
models/deep-research-max-preview-04-2026      Deep Research Max Preview (Apr-21-2026)
models/deep-research-preview-04-2026          Deep Research Preview (Apr-21-2026)
models/deep-research-pro-preview-12-2025      Deep Research Pro Preview (Dec-12-2025)
models/gemini-2.5-computer-use-preview-10-2025 Gemini 2.5 Computer Use Preview 10-2025
models/gemini-2.5-flash                       Gemini 2.5 Flash
models/gemini-2.5-flash-image                 Nano Banana
models/gemini-2.5-flash-lite                  Gemini 2.5 Flash-Lite
models/gemini-2.5-flash-preview-tts           Gemini 2.5 Flash Preview TTS
models/gemini-2.5-pro                         Gemini 2.5 Pro
models/gemini-2.5-pro-preview-tts             Gemini 2.5 Pro Preview TTS
models/gemini-3-flash-preview                 Gemini 3 Flash Preview
models/gemini-3-pro-image                     Nano Banana Pro
models/gemini-3-pro-image-preview             Nano Banana Pro
models/gemini-3.1-flash-image                 Nano Banana 2
models/gemini-3.1-flash-image-preview         Nano Banana 2
models/gemini-3.1-flash-lite                  Gemini 3.1 Flash Lite
models/gemini-3.1-flash-lite-image            Nano Banana 2 Lite
models/gemini-3.1-flash-lite-preview          Gemini 3.1 Flash Lite Preview
models/gemini-3.1-flash-tts-preview           Gemini 3.1 Flash TTS Preview
models/gemini-3.1-pro-preview                 Gemini 3.1 Pro Preview
models/gemini-3.1-pro-preview-customtools     Gemini 3.1 Pro Preview Custom Tools
models/gemini-3.5-flash                       Gemini 3.5 Flash
models/gemini-3.5-flash-lite                  Gemini 3.5 Flash Lite
models/gemini-3.5-transcribe                  Gemini 3.5 Transcribe
models/gemini-3.6-flash                       Gemini 3.6 Flash
models/gemini-3.7-flash                       Gemini 3.7 Flash
models/gemini-3.8-flash                       Gemini 3.8 Flash
models/gemini-3.8-flash-lite-tts              Gemini 3.8 Flash Lite TTS
models/gemini-3.8-flash-tts                   Gemini 3.8 Flash TTS
models/gemini-flash-latest                    Gemini Flash Latest
models/gemini-flash-lite-latest               Gemini Flash-Lite Latest
models/gemini-omni-1.1-flash                  Gemini Omni 1.1 Flash
models/gemini-omni-flash-preview              Gemini Omni Flash Preview
models/gemini-pro-latest                      Gemini Pro Latest
models/gemini-robotics-er-2-preview           Gemini Robotics-ER 2 Preview
models/gemma-4-26b-a4b-it                     Gemma 4 26B A4B IT
models/gemma-4-31b-it                         Gemma 4 31B IT
models/lyria-3-clip-preview                   Lyria 3 Clip Preview
models/lyria-3-pro-preview                    Lyria 3 Pro Preview
models/lyria-3.5                              Lyria 3.5
models/nano-banana-pro-preview                Nano Banana Pro
```

## Prueba real de generacion
```
[X]   gemini-2.5-flash         -> HTTP 404 {   "error": {     "code": 404,     "message": "This model models/gemini-2.5-flash is no longer available to new users. Please update your code to use models/gemini-3.8-flash for the latest features a
[X]   gemini-3.8-flash         -> HTTP 503 {   "error": {     "code": 503,     "message": "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.",     "status": "UNAVAILABLE"   } } 
[X]   gemini-flash-latest      -> HTTP 503 {   "error": {     "code": 503,     "message": "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.",     "status": "UNAVAILABLE"   } } 
[X]   gemini-2.0-flash         -> HTTP 404 {   "error": {     "code": 404,     "message": "This model models/gemini-2.0-flash is no longer available. Please update your code to use models/gemini-3.8-flash for the latest features and improvemen
[X]   gemini-3.8-flash-lite    -> HTTP 404 {   "error": {     "code": 404,     "message": "models/gemini-3.8-flash-lite is not found for API version v1beta, or is not supported for generateContent. Call ModelService.ListModels to see the list 
```
