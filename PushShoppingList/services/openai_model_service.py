def supports_custom_temperature(model):
    normalized_model = str(model or "").strip().lower()
    return not normalized_model.startswith("gpt-5")
