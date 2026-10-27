## 1. Sơ đồ luồng (flowchart)

```mermaid
flowchart TD
    A(["Nhà xe nhắn thông tin xe vào nhóm GMF"])
    B["ZOA tiếp nhận sự kiện và gửi dữ liệu về Service"]
    C{"Webhook hợp lệ?"}
    Z(["Kết thúc"])
    D{"Tin đã xử lý chưa?"}
    E["Lưu message_id, group_id, sender_id (raw_messages)"]
    F{"Kiểm tra người chat có thuộc nhà xe không?"}
    G["Tách thông tin: cont, seal, biển số, tài xế, SĐT, giờ đến, loại"]
    H{"Có thông tin cont (biển số, loại, giờ)?"}
    I["Tìm shipping theo cont"]
    J{"Tìm thấy shipping và đúng nhà xe?"}
    K["Báo ĐHVT xử lý"]
    L{"Thông tin đầy đủ và chính xác?"}
    M["Nhắn nhà xe bổ sung thông tin"]
    N["Tạo thông báo theo template"]
    O["Gửi thông báo vào nhóm khách"]
    P{"Gửi thành công?"}
    Q["Ghi log, cập nhật status trong shipping"]
    R["Báo ĐHVT gửi thủ công"]

    A --> B
    B --> C
    C -->|Không| Z
    C -->|Có| D
    D -->|Rồi| Z
    D -->|Chưa| E
    E --> F
    F -->|Không| Z
    F -->|Có| G
    G --> H
    H -->|Không| Z
    H -->|Có| I
    I --> J
    J -->|Không| K
    K --> Z
    J -->|Có| L
    L -->|Không| M
    M --> A
    L -->|Có| N
    N --> O
    O --> P
    P -->|Có| Q
    P -->|Không| R
    R --> Q
    Q --> Z
```

## 2. Sơ đồ tuần tự (sequence)

### 2a. Luồng chính, thông tin đủ và gửi khách thành công

```mermaid
sequenceDiagram
    autonumber
    actor NX as Nhà xe
    participant ZOA as Zalo OA / nhóm GMF nhà xe
    participant WH as Webhook API
    participant CA as Cache carrier_senders
    participant DB as Database
    participant Q as Hàng đợi
    participant SV as Service xử lý (gồm parser)
    participant ZK as Nhóm GMF khách
    actor KH as Khách hàng
    actor AD as Admin (ĐHVT)

    Note over NX,AD: Giai đoạn 1 - Webhook: xác thực, lọc, lưu, đẩy hàng đợi
    NX->>ZOA: Nhắn thông tin xe vào nhóm GMF
    ZOA->>WH: Webhook (message_id, group_id, sender_id, nội dung, timestamp)
    WH->>WH: Xác thực chữ ký

    alt Chữ ký sai
        WH->>WH: Ghi log (thời gian, IP, header)
        WH->>AD: Cảnh báo Admin (gom nhóm, giới hạn tần suất)
        WH-->>ZOA: 401 (body trống)
    else Chữ ký đúng
        WH->>WH: Lọc loại sự kiện (chỉ tin nhắn văn bản trong nhóm)
        alt Không phải tin văn bản trong nhóm
            WH-->>ZOA: 200 OK, bỏ qua
        else Là tin văn bản trong nhóm
            WH->>CA: Tra group_id, sender_id
            alt group_id không thuộc nhà xe nào
                CA-->>WH: Không có
                WH-->>ZOA: 200 OK, bỏ qua (không lưu)
            else group_id hợp lệ nhưng sender_id lạ
                CA-->>WH: Nhóm có, người gửi chưa đăng ký
                WH->>DB: Ghi log ngắn (message_id, group_id, sender_id, thời gian)
                WH->>AD: Cảnh báo nhẹ: có người lạ trong nhóm nhà xe, cần thêm sender
                WH-->>ZOA: 200 OK, bỏ qua
            else Hợp lệ
                CA-->>WH: carrier_id
                WH->>DB: INSERT raw_messages (carrier_id, status pending) ON CONFLICT DO NOTHING
                alt Chèn được 1 dòng (tin mới)
                    WH->>Q: Đẩy job (message_id)
                else Chèn 0 dòng (tin trùng)
                    Note over WH: Bỏ qua, không đẩy hàng đợi
                end
                WH-->>ZOA: 200 OK
            end
        end
    end

    Note over NX,AD: Giai đoạn 2 - Service xử lý lấy job từ hàng đợi
    Q->>SV: Lấy job (message_id)
    SV->>DB: Đọc raw_messages (đã có carrier_id)
    SV->>SV: Parse: tách khối xe, cont, seal, biển số, tài xế, SĐT, giờ đến
    SV->>SV: Chuẩn hóa, kiểm tra check digit cont, giải giờ theo timestamp

    alt Không có số cont
        SV->>DB: status = bỏ qua (chat thường), không phản hồi
    else Có số cont
        loop Mỗi xe trong tin
            SV->>DB: Tìm shipping theo cont (kèm khách, kênh GMF khách, nhà xe được giao)
            DB-->>SV: shipping_id, customer_id, group_id nhóm GMF khách, carrier_id
            alt Không có shipping hoặc sai nhà xe
                SV->>DB: Trạng thái KHÔNG KHỚP, ghi log
                SV->>AD: Báo Admin xử lý, kèm tin gốc và lý do
            else Shipping khớp
                alt Thiếu hoặc sai dữ liệu
                    SV->>DB: Trạng thái CHỜ BỔ SUNG
                    SV->>ZOA: Nhắn nhóm nhà xe nêu rõ thiếu gì, kèm cont
                    Note over NX,SV: Nhà xe nhắn bổ sung thì vào webhook mới, gộp vào chuyến cũ theo cont
                else Đủ và đúng
                    SV->>DB: Kiểm tra đã gửi (shipping_id, cont)
                    alt Chưa gửi
                        SV->>DB: Lấy template và thông tin khách (tên, người nhận, kênh GMF)
                        SV->>SV: Render THÔNG BÁO XE TRẢ HÀNG (dữ liệu khách + dữ liệu xe)
                        SV->>ZK: Gửi vào group_id của khách (lấy từ shipping)
                        alt Gửi thành công
                            ZK-->>SV: OK
                            ZK-->>KH: Hiển thị thông báo xe
                            SV->>DB: Trạng thái ĐÃ GỬI, ghi send_log (group_id, nội dung, thời gian)
                        else Gửi lỗi (retry tối đa 3 lần)
                            SV->>DB: Trạng thái LỖI GỬI, ghi log
                            SV->>AD: Báo Admin gửi thủ công
                            AD->>ZK: Gửi tay
                            AD->>DB: Đánh dấu ĐÃ GỬI TAY (tránh gửi trùng)
                        end
                    else Đã gửi, thông tin không đổi
                        SV->>DB: Bỏ qua, ghi log, cập nhật status shipping,..
                    end
                end
            end
        end
        SV->>DB: raw_messages.status = done
    end
```

### 2b. Các nhánh ngoại lệ

## 1. Nhà xe sửa / đổi tài xế sau khi đã gửi khách

```mermaid
sequenceDiagram
    autonumber
    actor NX as Nhà xe
    participant ZOA as Zalo OA / nhóm GMF nhà xe
    participant SV as Service xử lý
    participant DB as Database
    participant ZK as Nhóm GMF khách
    actor KH as Khách hàng
    actor AD as Admin (ĐHVT)

    Note over NX,AD: Tin của nhà xe đã qua webhook: xác thực, lọc nhà xe, chống trùng message_id
    NX->>ZOA: Nhắn thông tin sửa (ví dụ đổi tài xế cho cont X)
    ZOA->>SV: Tin được xử lý từ hàng đợi
    SV->>SV: Parse tin (cont, các trường thay đổi, từ khóa sửa/đổi/thay)

    alt Có từ khóa sửa nhưng không có số cont
        SV->>ZOA: Hỏi nhà xe: sửa cho cont nào?
        SV->>AD: Báo Admin có tin sửa chưa rõ cont, kèm tin gốc
    else Có số cont
        SV->>DB: Tìm shipping theo cont, lấy bản đang hiệu lực đã gửi khách (trip_versions)
        DB-->>SV: Shipping, khách, bản đang hiệu lực (ví dụ v1), trạng thái chuyến

        alt Chưa có bản nào đã gửi khách
            Note over SV: Không phải cập nhật, đi theo luồng chính
        else Đã có bản gửi khách
            SV->>SV: Update: trường nhà xe nhắn thay trường cũ, trường không nhắc giữ nguyên
            SV->>SV: Kiểm tra dữ liệu mới (biển số, SĐT, tên tài xế, seal)

            alt Dữ liệu mới thiếu hoặc sai
                SV->>DB: Ghi bản nháp CHỜ BỔ SUNG, giữ bản cũ đang hiệu lực
                SV->>ZOA: Nhắn nhà xe nêu rõ thiếu hoặc sai gì, kèm cont
                SV->>AD: Báo Admin: cont X đang đổi thông tin nhưng chưa đủ, khách vẫn đang giữ bản cũ
            else Dữ liệu mới hợp lệ
                SV->>SV: So sánh với bản đang hiệu lực (biển số, tài xế, SĐT, seal, giờ đến)

                alt Không có thay đổi
                    SV->>DB: Ghi log, bỏ qua (nhà xe nhắn lại thông tin cũ)
                else Có thay đổi
                    alt Chuyến đã hoàn tất hoặc xe đã đến kho
                        SV->>DB: Trạng thái CHỜ ADMIN
                        SV->>AD: Báo Admin quyết định, kèm bản cũ và bản mới
                    else Chuyến còn hiệu lực
                        SV->>DB: Lưu bản mới (version tăng 1), đánh dấu bản cũ bị thay thế
                        SV->>DB: Lấy template CẬP NHẬT và group_id GMF khách từ shipping
                        SV->>SV: Render THÔNG BÁO CẬP NHẬT (ghi rõ chỗ đổi: tài xế cũ sang tài xế mới, ...)
                        SV->>ZK: Gửi vào group_id của khách

                        alt Gửi thành công
                            ZK-->>SV: OK
                            ZK-->>KH: Hiển thị thông báo cập nhật
                            SV->>DB: ĐÃ GỬI bản mới, ghi send_log
                            SV->>ZOA: Xác nhận với nhà xe: đã cập nhật cont X
                            SV->>AD: Báo Admin (thông tin): đã gửi cập nhật cho khách
                        else Gửi lỗi (retry tối đa 3 lần)
                            SV->>DB: LỖI GỬI, ghi log
                            SV->>AD: Báo Admin gửi thủ công, kèm nội dung đã soạn
                            AD->>ZK: Gửi tay
                            AD->>DB: Đánh dấu ĐÃ GỬI TAY (tránh gửi trùng)
                        end
                    end
                end
            end
        end
    end
```

## 2. Các nhánh ngoại lệ còn lại

```mermaid
sequenceDiagram
    autonumber
    actor NX as Nhà xe
    participant ZOA as Zalo OA / nhóm GMF nhà xe
    participant SV as Service xử lý
    participant DB as Database
    participant ZK as Nhóm GMF khách
    actor AD as Admin (ĐHVT)

    Note over NX,AD: A. Thiếu hoặc sai dữ liệu lần đầu, rồi nhà xe bổ sung
    NX->>ZOA: Nhắn thông tin xe thiếu seal
    ZOA->>SV: Tin từ hàng đợi
    SV->>DB: Trạng thái CHỜ BỔ SUNG
    SV->>ZOA: Nhắn nhóm nhà xe: cont X còn thiếu số seal
    NX->>ZOA: Nhắn bổ sung số seal
    ZOA->>SV: Tin từ hàng đợi
    SV->>DB: Gộp vào chuyến cũ theo cont
    SV->>ZK: Gửi thông báo cho khách
    SV->>DB: ĐÃ GỬI

    Note over NX,AD: B. Không tìm thấy shipping hoặc sai nhà xe
    NX->>ZOA: Nhắn thông tin xe
    ZOA->>SV: Tin từ hàng đợi
    SV->>DB: Tìm shipping theo cont
    DB-->>SV: Không có, hoặc nhà xe không khớp
    SV->>DB: Trạng thái KHÔNG KHỚP
    SV->>AD: Báo Admin xử lý, kèm tin gốc và lý do

    Note over NX,AD: C. Gửi khách lỗi
    SV->>ZK: Gửi thông báo
    ZK-->>SV: Lỗi
    loop Retry tối đa 3 lần
        SV->>ZK: Gửi lại
    end
    SV->>DB: Trạng thái LỖI GỬI
    SV->>AD: Báo Admin gửi thủ công
```

## 3. Quá trình lọc và xử lý
