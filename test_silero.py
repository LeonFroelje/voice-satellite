import onnxruntime as ort


def inspect_onnx_model(model_path):
    print(f"Inspecting: {model_path}\n{'-' * 30}")

    # Load the model
    session = ort.InferenceSession(model_path)
    meta = session.get_modelmeta()

    # 1. Check Metadata Map (Silero usually embeds the version here)
    print("--- Metadata ---")
    print(f"Version/Producer: {meta.producer_name} v{meta.version}")
    print(f"Custom Map: {meta.custom_metadata_map}")

    # 2. Check Expected Inputs
    print("\n--- Expected Inputs ---")
    for idx, input_meta in enumerate(session.get_inputs()):
        print(
            f"Input {idx}: Name='{input_meta.name}', Shape={input_meta.shape}, Type={input_meta.type}"
        )


def main():
    inspect_onnx_model("assets/models/silero_vad.onnx")
