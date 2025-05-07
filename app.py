# app.py - Ứng dụng Web Flask để điều khiển và hiển thị trạng thái Simulator
import os
import json
import time
import threading
import socket
from flask import Flask, render_template, request, jsonify, Response
from pythonosc import udp_client
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer, ThreadingOSCUDPServer

# Cấu hình
SIMULATOR_IP = "127.0.0.1"  # IP của Color Signal Generation System
SIMULATOR_PORT = 9090  # Port OSC để gửi điều khiển tới simulator
WEB_OSC_PORT = 5005  # Port để nhận dữ liệu từ simulator
WEB_SERVER_PORT = 5000  # Port web server

app = Flask(__name__)
app.config['SECRET_KEY'] = 'color_signal_system_key'
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Biến toàn cục để lưu trữ trạng thái
simulator_state = {
    'scenes': {},
    'current_scene': None,
    'current_effect': None,
    'current_palette': None,
    'segments': {},
    'led_colors': [],
    'last_update': time.time(),
    'is_connected': False
}

# Khóa cho thread safety
state_lock = threading.Lock()

# Khởi tạo OSC client để gửi lệnh tới simulator
osc_client = udp_client.SimpleUDPClient(SIMULATOR_IP, SIMULATOR_PORT)


# Hàm gửi OSC message
def send_osc_message(address, *args):
    try:
        osc_client.send_message(address, args)
        return True
    except Exception as e:
        print(f"Lỗi khi gửi OSC message: {e}")
        return False


# --- Xử lý OSC Server để nhận dữ liệu từ simulator ---

# Xử lý nhận trạng thái scene
def handle_scene_state(address, *args):
    with state_lock:
        scene_id = int(address.split('/')[-1])
        simulator_state['scenes'][scene_id] = args[0]
        simulator_state['last_update'] = time.time()
        simulator_state['is_connected'] = True


# Xử lý nhận trạng thái scene hiện tại
def handle_current_scene(address, *args):
    with state_lock:
        simulator_state['current_scene'] = args[0]
        simulator_state['last_update'] = time.time()
        simulator_state['is_connected'] = True


# Xử lý nhận trạng thái effect hiện tại
def handle_current_effect(address, *args):
    with state_lock:
        simulator_state['current_effect'] = args[0]
        simulator_state['last_update'] = time.time()
        simulator_state['is_connected'] = True


# Xử lý nhận trạng thái segment
def handle_segment_state(address, *args):
    with state_lock:
        parts = address.split('/')
        scene_id = int(parts[2])
        effect_id = int(parts[4])
        segment_id = int(parts[6])

        if scene_id not in simulator_state['segments']:
            simulator_state['segments'][scene_id] = {}

        if effect_id not in simulator_state['segments'][scene_id]:
            simulator_state['segments'][scene_id][effect_id] = {}

        simulator_state['segments'][scene_id][effect_id][segment_id] = args[0]
        simulator_state['last_update'] = time.time()
        simulator_state['is_connected'] = True


# Xử lý nhận màu LED
def handle_led_colors(address, *args):
    with state_lock:
        # Chuyển đổi dữ liệu binary thành danh sách RGB
        if isinstance(args[0], bytes):
            colors = []
            data = args[0]
            for i in range(0, len(data), 4):  # Mỗi LED là 4 byte (R,G,B,0)
                if i + 2 < len(data):  # Đảm bảo có đủ dữ liệu
                    colors.append([data[i], data[i + 1], data[i + 2]])
            simulator_state['led_colors'] = colors
        else:
            simulator_state['led_colors'] = args[0]

        simulator_state['last_update'] = time.time()
        simulator_state['is_connected'] = True


# Thiết lập OSC dispatcher
dispatcher = Dispatcher()
dispatcher.map("/scene/*/state", handle_scene_state)
dispatcher.map("/current_scene", handle_current_scene)
dispatcher.map("/current_effect", handle_current_effect)
dispatcher.map("/scene/*/effect/*/segment/*/state", handle_segment_state)
dispatcher.map("/light/serial", handle_led_colors)
dispatcher.map("/led_colors", handle_led_colors)


# Khởi động OSC server trong thread riêng
def start_osc_server():
    try:
        server = ThreadingOSCUDPServer(("0.0.0.0", WEB_OSC_PORT), dispatcher)
        print(f"Bắt đầu OSC server tại port {WEB_OSC_PORT}")
        server.serve_forever()
    except socket.error as e:
        print(f"Không thể khởi động OSC server: {e}")


osc_thread = threading.Thread(target=start_osc_server)
osc_thread.daemon = True
osc_thread.start()


# --- Routes cho Flask Web Server ---

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/state')
def get_state():
    with state_lock:
        return jsonify(simulator_state)


@app.route('/api/scenes')
def get_scenes():
    # Gửi OSC message để yêu cầu danh sách scenes
    send_osc_message("/scene_manager/list_scenes")

    with state_lock:
        return jsonify({
            'scenes': simulator_state['scenes'],
            'current_scene': simulator_state['current_scene']
        })


@app.route('/api/effects/<int:scene_id>')
def get_effects(scene_id):
    # Gửi OSC message để yêu cầu danh sách effects
    send_osc_message(f"/scene/{scene_id}/list_effects")

    with state_lock:
        if scene_id in simulator_state['segments']:
            return jsonify({
                'effects': list(simulator_state['segments'][scene_id].keys())
            })
        return jsonify({'effects': []})


@app.route('/api/palettes/<int:scene_id>')
def get_palettes(scene_id):
    # Gửi OSC message để yêu cầu danh sách palettes
    send_osc_message(f"/scene/{scene_id}/list_palettes")

    with state_lock:
        # Giả định rằng palettes được lưu trong scenes
        if str(scene_id) in simulator_state['scenes']:
            scene_data = simulator_state['scenes'][str(scene_id)]
            if 'palettes' in scene_data:
                return jsonify({'palettes': scene_data['palettes']})
        return jsonify({'palettes': ['A', 'B', 'C', 'D', 'E']})  # Mặc định


@app.route('/api/segments/<int:scene_id>/<int:effect_id>')
def get_segments(scene_id, effect_id):
    # Gửi OSC message để yêu cầu danh sách segments
    send_osc_message(f"/scene/{scene_id}/effect/{effect_id}/list_segments")

    with state_lock:
        if (scene_id in simulator_state['segments'] and
                effect_id in simulator_state['segments'][scene_id]):
            return jsonify({
                'segments': list(simulator_state['segments'][scene_id][effect_id].keys())
            })
        return jsonify({'segments': []})


@app.route('/api/led_colors')
def get_led_colors():
    with state_lock:
        return jsonify({'colors': simulator_state['led_colors']})


@app.route('/api/send_command', methods=['POST'])
def send_command():
    data = request.json
    if not data or 'address' not in data:
        return jsonify({'success': False, 'error': 'Thiếu địa chỉ OSC'})

    address = data['address']
    args = data.get('args', [])

    success = send_osc_message(address, *args)
    return jsonify({'success': success})


@app.route('/api/change_palette', methods=['POST'])
def change_palette():
    data = request.json
    if not data or 'scene_id' not in data or 'palette' not in data:
        return jsonify({'success': False, 'error': 'Thiếu thông tin scene hoặc palette'})

    scene_id = data['scene_id']
    palette = data['palette']
    effect_id = data.get('effect_id')

    if effect_id:
        # Thay đổi palette cho effect cụ thể
        success = send_osc_message(f"/scene/{scene_id}/effect/{effect_id}/change_palette", palette)
    else:
        # Thay đổi palette cho toàn bộ scene
        success = send_osc_message(f"/scene/{scene_id}/change_palette", palette)

    return jsonify({'success': success})


@app.route('/api/change_effect', methods=['POST'])
def change_effect():
    data = request.json
    if not data or 'scene_id' not in data or 'effect_id' not in data:
        return jsonify({'success': False, 'error': 'Thiếu thông tin scene hoặc effect'})

    scene_id = data['scene_id']
    effect_id = data['effect_id']

    success = send_osc_message(f"/scene/{scene_id}/change_effect", effect_id)
    return jsonify({'success': success})


@app.route('/api/save_scene', methods=['POST'])
def save_scene():
    data = request.json
    if not data or 'scene_id' not in data or 'file_path' not in data:
        return jsonify({'success': False, 'error': 'Thiếu thông tin scene hoặc đường dẫn file'})

    scene_id = data['scene_id']
    file_path = data['file_path']

    success = send_osc_message(f"/scene/{scene_id}/save_effects", file_path)
    return jsonify({'success': success})


@app.route('/api/load_scene', methods=['POST'])
def load_scene():
    data = request.json
    if not data or 'file_path' not in data:
        return jsonify({'success': False, 'error': 'Thiếu đường dẫn file'})

    file_path = data['file_path']
    scene_id = data.get('scene_id')

    # Đầu tiên đọc nội dung file JSON để biết những gì sẽ được tải
    try:
        # Đảm bảo đường dẫn hợp lệ
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'error': f'Không tìm thấy file: {file_path}'})

        # Đọc file JSON
        with open(file_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)

        # Gửi lệnh tải scene đến simulator
        if scene_id:
            success = send_osc_message(f"/scene_manager/load_scene", file_path, scene_id)
        else:
            success = send_osc_message(f"/scene_manager/load_scene", file_path)

        if success:
            # Trả về thông tin scene từ file JSON
            return jsonify({
                'success': True,
                'scene_data': json_data,  # Gửi toàn bộ dữ liệu JSON trở lại cho client
                'message': 'Scene đã được tải thành công'
            })
        else:
            return jsonify({'success': False, 'error': 'Không thể gửi lệnh OSC'})

    except Exception as e:
        return jsonify({'success': False, 'error': f'Lỗi khi tải scene: {str(e)}'})


@app.route('/api/update_segment', methods=['POST'])
def update_segment():
    data = request.json
    if not data or 'scene_id' not in data or 'effect_id' not in data or 'segment_id' not in data:
        return jsonify({'success': False, 'error': 'Thiếu thông tin scene, effect hoặc segment'})

    scene_id = data['scene_id']
    effect_id = data['effect_id']
    segment_id = data['segment_id']

    # Cập nhật từng thuộc tính
    success = True
    for param, value in data.get('params', {}).items():
        result = send_osc_message(
            f"/scene/{scene_id}/effect/{effect_id}/segment/{segment_id}/{param}",
            value
        )
        success = success and result

    return jsonify({'success': success})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=WEB_SERVER_PORT, debug=True)
