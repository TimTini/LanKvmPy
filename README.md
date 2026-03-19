# LAN KVM Python

LAN KVM tối giản cho 2 máy Windows cùng mạng nội bộ. Mỗi máy chạy cùng một app Python, dùng một TCP connection, xác thực bằng shared secret, và chuyển chuột/bàn phím khi chuột chạm mép màn hình đã cấu hình.

## Scope v1

- Windows -> Windows
- Chạy thủ công trong user session
- Chỉ mouse + keyboard
- Chuyển focus khi chạm `left/right/top/bottom`
- Delay mép màn hình để tránh nhảy chuột ngoài ý muốn
- Xác thực bằng HMAC + MessagePack

## Giới hạn hiện tại

- Không hỗ trợ màn hình login hoặc UAC secure desktop
- Không hỗ trợ clipboard, file transfer, nhiều máy, auto-discovery
- Một số game hoặc app dùng raw input/anti-cheat có thể không nhận input inject như desktop thường
- Nên dùng LAN ổn định; Wi-Fi yếu sẽ làm chuột giật hoặc trễ

## Cài đặt

```powershell
python -m pip install -e .
```

Nếu máy chưa có alias `python`, dùng đường dẫn Python thật hoặc `py -3.12`.

## Chạy

1. Copy `config.sample.toml` thành `config.toml` trên từng máy.
2. Chỉnh `role`, `peer_host`, `handoff_edge`, `entry_edge`, `shared_secret`.
3. Mở firewall cho TCP port đã dùng, mặc định `24801`.
4. Chạy app:

```powershell
python main.py
```

Mặc định app sẽ tự dùng `config.toml` trong thư mục hiện tại và log level `DEBUG`.
Nếu cần override vẫn có thể chạy `python main.py --config other.toml --log-level INFO`.

## Cấu hình tối thiểu

```toml
machine_id = "machine-a"
role = "dialer"
peer_host = "192.168.1.31"
listen_host = "0.0.0.0"
listen_port = 24801
handoff_edge = "right"
entry_edge = "right"
switch_delay_ms = 200
shared_secret = "replace-this-secret"
heartbeat_ms = 400
dead_zone_px = 4
max_mouse_hz = 120
reconnect_ms = 1000
failsafe_hotkey = ["ctrl", "alt", "f12"]
```

## Layout ví dụ

- Máy A: `handoff_edge = "right"`, `entry_edge = "right"`
- Máy B: `handoff_edge = "left"`, `entry_edge = "left"`

Khi chuột ở máy A chạm mép phải đủ `switch_delay_ms`, quyền điều khiển sẽ chuyển sang máy B ở mép trái. Khi chuột trên máy B chạm mép trái, quyền điều khiển trả về A ở mép phải.
