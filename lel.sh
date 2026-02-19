#!/usr/bin/env bash

# Define colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Your list of requirements
REQUIREMENTS="annotated-types==0.7.0
av==16.1.0
certifi==2026.1.4
charset-normalizer==3.4.4
flatbuffers==25.12.19
gevent==25.9.1
greenlet==3.3.1
idna==3.11
joblib==1.5.3
mpmath==1.3.0
numpy==1.26.4
onnxruntime==1.24.1
openwakeword==0.6.0
packaging==26.0
protobuf==6.33.5
PyAudio==0.2.14
pydantic==2.12.5
pydantic-settings==2.13.0
pydantic_core==2.41.5
pydub==0.25.1
python-dotenv==1.2.1
requests==2.32.5
scikit-learn==1.8.0
scipy==1.17.0
sympy==1.14.0
tflite-runtime==2.14.0
threadpoolctl==3.6.0
tqdm==4.67.3
typing-inspection==0.4.2
typing_extensions==4.15.0
urllib3==2.6.3
websocket-client==1.9.0
zope.event==6.1
zope.interface==8.2"

echo "Checking nixpkgs for python packages..."
echo "---------------------------------------"

# Loop through each line
echo "$REQUIREMENTS" | while read -r line; do
    # 1. Extract name (remove ==version)
    RAW_NAME=$(echo "$line" | cut -d'=' -f1)
    
    # 2. Convert to lowercase (Nix attributes are usually lowercase)
    NAME=$(echo "$RAW_NAME" | tr '[:upper:]' '[:lower:]')
    
    # 3. Handle common naming mismatches (pip -> nix)
    # Python packages in nix usually replace '.' or '_' with '-' or '_' depending on the maintainer
    # We will search specifically for python3Packages.<name>
    
    # Search logic: 
    # We grep strictly for the attribute path to avoid false positives from descriptions.
    RESULT=$(nix search nixpkgs "^$NAME$" 2>/dev/null)
    
    # If standard search fails, try replacing '.' with '_' (common in nix for zope, etc.)
    if [ -z "$RESULT" ] && [[ "$NAME" == *"."* ]]; then
        ALT_NAME=$(echo "$NAME" | tr '.' '_')
        RESULT=$(nix search nixpkgs "^$ALT_NAME$" 2>/dev/null)
        NAME="$ALT_NAME (originally $RAW_NAME)"
    fi

    if [ -n "$RESULT" ]; then
        echo -e "${GREEN}✔ Found:${NC} $NAME"
    else
        echo -e "${RED}✘ Missing:${NC} $NAME"
    fi
done
