# MiniMax H3 Turbo LoRA ComfyUI

**MiniMax H3 Turbo LoRA ComfyUI** runs **minimax h3** (33B omni-modal) locally in **ComfyUI**: **text-to-video**, **image-to-video**, **reference-to-video**, native stereo audio. **Turbo LoRA**, H3-VisualVAE / H3-AudioVAE. 4–15s at 768p.

<img width="749" height="267" alt="images1" src="https://github.com/user-attachments/assets/982676fe-7774-42c1-9a46-6cae8c6c0e37" />

<img width="736" height="271" alt="images2" src="https://github.com/user-attachments/assets/0525dde9-0f0e-4f7e-8364-aad9ce47d38a" />

<img width="1522" height="1432" alt="image" src="https://github.com/user-attachments/assets/d7f3f792-dd7d-41f6-87a9-1f9484dac830" />


## What's new in v1.1 (August 28, 2026)
- ComfyUI 0.32 node ids
- Turbo LoRA loader
- T2V / I2V / R2V templates
- 2K regenerate node

<img width="596" height="335" alt="images3" src="https://github.com/user-attachments/assets/0aedd15e-1ecc-4eb2-bb58-e7c5796ca720" />

<img width="547" height="365" alt="images10" src="https://github.com/user-attachments/assets/99b44d71-d94f-4660-b722-5bb5f15196c4" />


## Key Features
- **H3ModelLoader** — FL2VA / Ref2VA
- **H3TextToVideo** / **H3ImageToVideo** / **H3ReferenceToVideo**
- **H3VAEDecode** + stereo audio
- Optional SGLang serve

<img width="592" height="337" alt="images4" src="https://github.com/user-attachments/assets/aff8c352-46ac-4c53-ad1f-c1e61aafee60" />



## Turbo LoRA setup
Drop the LoRA next to the H3 weights, enable the turbo node, keep CFG low.

<img width="1672" height="941" alt="images5" src="https://github.com/user-attachments/assets/0267e300-0092-4946-9149-94cc07d8bba1" />


## Getting Started
1. Download v1.1.
2. `huggingface-cli` pull MiniMax H3 (+ turbo LoRA).
3. Copy custom nodes into ComfyUI.
4. Load T2V / I2V / R2V workflow.

<img width="686" height="386" alt="images6" src="https://github.com/user-attachments/assets/6edf64e5-d95f-454c-a5d1-140a7845bb64" />
<img width="1659" height="1068" alt="images7" src="https://github.com/user-attachments/assets/45d1cdb1-cf49-43b6-9013-aff5cbabde14" />



## FAQ

**VRAM?**
24 GB class for 768p shorts. Quantize or SGLang if tight.

**Audio?**
Native stereo from H3-AudioVAE.



## Requirements
ComfyUI 0.32 · NVIDIA 16 GB+ recommended · Hugging Face weights

## License
MiniMax weights + MIT nodes — Copyright © 2026 MiniMaxH3ComfyUI

<img width="855" height="359" alt="images9" src="https://github.com/user-attachments/assets/a1eaf3e0-a484-4948-a226-c7afe91f3a85" />

