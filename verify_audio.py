import pyaudio

if __name__ == "__main__":
    p = pyaudio.PyAudio()
    for i in range(p.get_device_count()):
        dev_info = p.get_device_info_by_index(i)
        print(i, dev_info)
