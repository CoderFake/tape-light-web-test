# receiver.py - Script nhận dữ liệu LED từ simulator qua OSC để kiểm thử
import time
import argparse
import threading
import struct
from pythonosc import osc_server, dispatcher
from pythonosc.udp_client import SimpleUDPClient

# Cấu hình mặc định
DEFAULT_RECEIVE_PORT = 7000  # Port nhận dữ liệu LED từ simulator
DEFAULT_IP = "0.0.0.0"  # Xử lý các kết nối từ bất kỳ interface nào
DEFAULT_FEEDBACK_PORT = 9090  # Port gửi thông tin trạng thái về simulator

# Biến toàn cục
led_data = None
led_count = 0
last_update_time = time.time()
is_connected = False


# Xử lý dữ liệu LED nhận được
def handle_led_data(address, *args):
    global led_data, led_count, last_update_time, is_connected

    # Xử lý dữ liệu binary
    if len(args) > 0 and isinstance(args[0], bytes):
        binary_data = args[0]
        data_length = len(binary_data)
        led_count = data_length // 4  # Mỗi LED là 4 byte (R,G,B,0)

        # Chuyển đổi dữ liệu binary thành mảng màu RGB
        led_colors = []
        for i in range(0, data_length, 4):
            if i + 2 < data_length:  # Đảm bảo có đủ dữ liệu
                r, g, b, _ = struct.unpack("BBBB", binary_data[i:i + 4])
                led_colors.append([r, g, b])

        led_data = led_colors
        last_update_time = time.time()
        is_connected = True

        # In thông tin debug
        print(f"Đã nhận {led_count} LED - Thời điểm: {time.strftime('%H:%M:%S', time.localtime())}")


# Hàm in trạng thái LED dưới dạng ASCII art
def print_led_status():
    if led_data is None or len(led_data) == 0:
        print("Chưa nhận được dữ liệu LED")
        return

    # Chọn một số LED để hiển thị (không hiển thị tất cả để tránh quá nhiều output)
    display_count = min(20, len(led_data))
    step = max(1, len(led_data) // display_count)

    print("\n" + "=" * 60)
    print(f"Trạng thái LED ({len(led_data)} LEDs) - Hiển thị {display_count} LEDs:")
    print("-" * 60)

    # Hiển thị dạng số
    for i in range(0, len(led_data), step):
        if i < len(led_data):
            color = led_data[i]
            print(f"LED {i:3d}: R:{color[0]:3d} G:{color[1]:3d} B:{color[2]:3d}")

    # Hiển thị dạng biểu tượng màu (sử dụng ký tự ASCII)
    print("\nBiểu đồ LED:", end="")
    for i in range(0, len(led_data), step):
        if i < len(led_data):
            color = led_data[i]
            # Chọn ký tự dựa trên độ sáng
            brightness = (color[0] + color[1] + color[2]) / 3
            if brightness < 20:
                char = " "
            elif brightness < 85:
                char = "."
            elif brightness < 150:
                char = "+"
            elif brightness < 220:
                char = "*"
            else:
                char = "#"
            print(char, end="")
    print("\n" + "=" * 60)


# Gửi thông tin trạng thái về simulator
def send_status_to_simulator(client):
    global led_count, last_update_time, is_connected

    while True:
        current_time = time.time()
        # Kiểm tra kết nối
        if current_time - last_update_time > 5.0:
            if is_connected:
                print("Mất kết nối với simulator!")
                is_connected = False
        else:
            if not is_connected:
                print("Đã kết nối với simulator!")
                is_connected = True

        # Gửi thông tin trạng thái về simulator
        if is_connected:
            try:
                client.send_message("/receiver/status", [
                    is_connected,
                    led_count,
                    current_time - last_update_time
                ])
            except Exception as e:
                print(f"Lỗi khi gửi trạng thái: {e}")

        time.sleep(1.0)


def main():
    parser = argparse.ArgumentParser(description='LED Data Receiver')
    parser.add_argument('--ip', default=DEFAULT_IP, help=f'Địa chỉ IP để lắng nghe (mặc định: {DEFAULT_IP})')
    parser.add_argument('--port', type=int, default=DEFAULT_RECEIVE_PORT,
                        help=f'Port nhận dữ liệu LED (mặc định: {DEFAULT_RECEIVE_PORT})')
    parser.add_argument('--feedback-port', type=int, default=DEFAULT_FEEDBACK_PORT,
                        help=f'Port gửi thông tin trạng thái (mặc định: {DEFAULT_FEEDBACK_PORT})')
    parser.add_argument('--interval', type=float, default=1.0, help='Khoảng thời gian hiển thị trạng thái (giây)')
    args = parser.parse_args()

    # Thiết lập dispatcher
    disp = dispatcher.Dispatcher()
    disp.map("/light/serial", handle_led_data)

    # Khởi tạo OSC server
    server = osc_server.ThreadingOSCUDPServer((args.ip, args.port), disp)
    print(f"Đang lắng nghe dữ liệu LED tại {args.ip}:{args.port}")

    # Khởi tạo feedback client
    feedback_client = SimpleUDPClient("127.0.0.1", args.feedback_port)
    print(f"Gửi thông tin trạng thái về {args.feedback_port}")

    # Bắt đầu thread gửi trạng thái
    status_thread = threading.Thread(target=send_status_to_simulator, args=(feedback_client,))
    status_thread.daemon = True
    status_thread.start()

    # Bắt đầu thread hiển thị trạng thái
    def display_status_thread():
        while True:
            print_led_status()
            time.sleep(args.interval)

    display_thread = threading.Thread(target=display_status_thread)
    display_thread.daemon = True
    display_thread.start()

    # Bắt đầu server
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐang dừng receiver...")


if __name__ == "__main__":
    main()