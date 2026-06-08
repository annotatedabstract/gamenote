from gamenote.transcribe import _device_attempts


def test_auto_prefers_gpu_then_cpu():
    assert _device_attempts("auto") == [("cuda", "float16"), ("cpu", "int8")]


def test_cuda_also_falls_back_to_cpu():
    # "Force GPU" still falls back so a missing CUDA install doesn't brick the
    # app; the caller warns the user when the GPU did not engage.
    assert _device_attempts("cuda") == [("cuda", "float16"), ("cpu", "int8")]


def test_cpu_is_the_only_attempt():
    assert _device_attempts("cpu") == [("cpu", "int8")]


def test_blank_and_unknown_default_to_auto():
    assert _device_attempts("") == [("cuda", "float16"), ("cpu", "int8")]
    assert _device_attempts("something-else") == [("cuda", "float16"), ("cpu", "int8")]


def test_value_is_normalized():
    assert _device_attempts("  CPU  ") == [("cpu", "int8")]
