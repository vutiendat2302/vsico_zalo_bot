Mình vẽ theo luồng giai đoạn 1: nhà xe báo xe, bot join shipping theo số cont rồi gửi khách, còn lệnh đóng kết hợp để giai đoạn 2.

## 1. Sơ đồ luồng (flowchart)

```mermaid
flowchart TD
    A(["Nhà xe nhắn thông tin xe vào nhóm GMF"]) --> B["ZOA (lọc tin nhắn) tự động gửi response về Service"]
    B --> C{"Webhook hợp lệ?"}
    C -- "Không" --> Z(["Kết thúc"])
    C -- "Có" --> D{"Tin đã xử lý chưa?"}
    D -- "Rồi" --> Z
    D -- "Chưa" --> E["Lưu tin gốc"]
    E --> F{"Nhóm và người gửi thuộc nhà xe đăng ký?"}
    F -- "Không" --> Z
    F -- "Có" --> G["Tách thông tin: cont, seal, biển số, tài xế, SĐT, giờ đến, loại"]
    G --> H{"Có số cont?"}
    H -- "Không" --> Z
    H -- "Có" --> I["Tìm shipping theo số cont"]
    I --> J{"Tìm thấy shipping, đúng nhà xe?"}
    J -- "Không" --> K["Báo ĐHVT xử lý"] --> Z
    J -- "Có" --> L{"Thông tin đủ và đúng?"}
    L -- "Không" --> M["Nhắn nhà xe bổ sung"] --> A
    L -- "Có" --> N["Tạo thông báo theo template của khách"]
    N --> O["Gửi vào nhóm khách"]
    O --> P{"Gửi thành công?"}
    P -- "Có" --> Q["Ghi log"]
    P -- "Không" --> R["Báo ĐHVT gửi tay"] --> Q
    Q --> Z
```

## 2. Sơ đồ tuần tự (sequence)

### 2a. Luồng chính, thông tin đủ và gửi khách thành công

```mermaid
sequenceDiagram
    autonumber
    actor NX as Nhà xe
    participant ZG as Zalo OA / nhóm GMF nhà xe
    participant WH as Webhook Service
    participant Q as Hàng đợi
    participant PS as Parser
    participant DB as DB shipping và trips
    participant TP as Template
    participant ZK as Zalo OA / nhóm GMF khách
    actor KH as Khách hàng
    actor DH as ĐHVT

    NX->>ZG: Nhắn thông tin xe (cont, seal, biển số, tài xế, SĐT, giờ đến)
    ZG->>WH: Webhook (message_id, group_id, sender_id, nội dung, timestamp)
    WH->>WH: Xác thực chữ ký
    WH->>DB: Kiểm tra message_id, lưu raw_messages
    WH-->>ZG: 200 OK
    WH->>Q: Đẩy job xử lý

    Q->>DB: Kiểm tra group_id, sender_id thuộc nhà xe đăng ký
    DB-->>Q: Hợp lệ (carrier_id)

    Q->>PS: Gửi nội dung tin
    PS->>PS: Tách khối xe, regex, check digit cont, chuẩn hóa biển số và SĐT
    PS->>PS: Giải giờ đến theo timestamp tin nhắn
    PS-->>Q: Danh sách chuyến (JSON)

    loop Mỗi xe trong tin
        Q->>DB: Tìm shipping theo số cont
        DB-->>Q: shipping_id, khách, group_id khách, nhà xe được giao
        Q->>Q: Kiểm tra nhà xe khớp và dữ liệu đủ, đúng
        Q->>DB: Kiểm tra đã gửi (shipping_id, loại, cont)
        DB-->>Q: Chưa gửi
        Q->>TP: Lấy template theo khách và loại thông báo
        TP-->>Q: Nội dung THÔNG BÁO XE ĐÓNG hoặc TRẢ HÀNG
        Q->>ZK: Gửi tin vào group_id nhóm khách
        ZK-->>KH: Hiển thị thông báo xe
        ZK-->>Q: Kết quả gửi thành công
        Q->>DB: Cập nhật trips = ĐÃ GỬI, ghi send_log
    end
```

### 2b. Các nhánh ngoại lệ

```mermaid
sequenceDiagram
    autonumber
    actor NX as Nhà xe
    participant ZG as Zalo OA / nhóm GMF nhà xe
    participant Q as Service xử lý
    participant DB as DB shipping và trips
    participant ZK as Zalo OA / nhóm GMF khách
    actor DH as ĐHVT

    Note over NX,DH: Nhánh A: thiếu hoặc sai dữ liệu
    NX->>ZG: Nhắn thông tin xe thiếu seal
    ZG->>Q: Webhook
    Q->>DB: Lưu trips = CHỜ BỔ SUNG
    Q->>ZG: Nhắn lại nhóm nhà xe (cont X còn thiếu số seal)
    NX->>ZG: Nhắn bổ sung số seal
    ZG->>Q: Webhook
    Q->>DB: Gộp vào chuyến cũ theo cont
    Q->>ZK: Gửi thông báo cho khách
    Q->>DB: trips = ĐÃ GỬI

    Note over NX,DH: Nhánh B: không tìm thấy shipping hoặc sai nhà xe
    NX->>ZG: Nhắn thông tin xe
    ZG->>Q: Webhook
    Q->>DB: Tìm shipping theo cont
    DB-->>Q: Không có, hoặc nhà xe không khớp
    Q->>DB: trips = KHÔNG CÓ SHIPPING hoặc SAI NHÀ XE
    Q->>DH: Báo ĐHVT kèm tin gốc để xử lý

    Note over NX,DH: Nhánh C: nhà xe đổi xe hoặc tài xế sau khi đã gửi
    NX->>ZG: Nhắn thông tin mới, cùng cont
    ZG->>Q: Webhook
    Q->>DB: So sánh với bản đã gửi, có thay đổi
    Q->>ZK: Gửi thông báo CẬP NHẬT, ghi rõ chỗ đổi
    Q->>DB: Ghi send_log bản mới

    Note over NX,DH: Nhánh D: gửi khách lỗi
    Q->>ZK: Gửi tin
    ZK-->>Q: Lỗi
    loop Retry tối đa 3 lần
        Q->>ZK: Gửi lại
    end
    Q->>DB: trips = LỖI GỬI
    Q->>DH: Báo ĐHVT gửi thất bại, cần gửi tay
```

## 3. Sơ đồ trạng thái chuyến (tham khảo)

```mermaid

stateDiagram    
    direction TB

    [*] --> NHAN_TIN
    NHAN_TIN --> KHONG_CO_SHIPPING: join that bai
    NHAN_TIN --> SAI_NHA_XE: nha xe khong khop
    NHAN_TIN --> CHO_BO_SUNG: thieu hoac sai du lieu

    CHO_BO_SUNG --> SAN_SANG: nha xe bo sung du
    NHAN_TIN --> SAN_SANG: du va hop le
    KHONG_CO_SHIPPING --> SAN_SANG: DHVT xu ly xong
    SAI_NHA_XE --> SAN_SANG: DHVT xac nhan

    SAN_SANG --> DA_GUI: gui khach thanh cong
    SAN_SANG --> LOI_GUI: gui loi sau 3 lan
    LOI_GUI --> DA_GUI: DHVT gui tay hoac retry

    DA_GUI --> DA_GUI: co thay doi - gui ban CAP NHAT
    DA_GUI --> [*]

    note right of DA_GUI
        Khi có thay đổi sau khi gửi
        sẽ gửi bản CẬP NHẬT (self-loop)
    end note


``` 