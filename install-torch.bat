call venv\Scripts\activate.bat
pip uninstall -y torch
pip install torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0 --index-url https://download.pytorch.org/whl/cu124 --force-reinstall --no-deps

PAUSE