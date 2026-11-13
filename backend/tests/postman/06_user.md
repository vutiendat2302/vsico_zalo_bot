# TÀI LIỆU KIỂM THỬ POSTMAN & CURL: PHÂN HỆ XÁC THỰC (AUTH) & QUẢN LÝ TÀI KHOẢN (USERS)

Tài liệu này hướng dẫn chi tiết từng bước thiết lập trên Postman (Tab Body, Params, Headers, Scripts) và câu lệnh cURL tương đương để kiểm thử toàn bộ API Xác thực (`/api/auth`) và Quản lý Người dùng (`/api/users`).

Tất cả các định danh người dùng trong hệ thống tuân thủ định dạng Snowflake ID 64-bit dạng chuỗi. Phân quyền bao gồm hai vai trò: `admin` (Quản trị viên) và `dhvt` (Điều hành vận tải).

---

## 1. Cấu hình Môi trường Postman (Environment Variables)

Khởi tạo một Postman Environment có tên `VSICO_Local_Dev` (hoặc cấu hình tại tab **Globals**) với các biến sau:

| Tên biến        | Giá trị mẫu            | Mô tả                                                          |
| :---------------- | :------------------------ | :--------------------------------------------------------------- |
| `baseUrl`       | `http://localhost:8000` | Địa chỉ máy chủ FastAPI Backend                             |
| `adminUsername` | `admin`                 | Tên đăng nhập mặc định                                    |
| `adminPassword` | `123456`                | Mật khẩu mặc định hệ thống                                |
| `authToken`     | *(để trống)*         | Tự động ghi nhận JWT Access Token sau khi login thành công |
| `createdUserId` | *(để trống)*         | Tự động ghi nhận Snowflake ID người dùng mới tạo        |

---

## 2. Lưu Ý Quan Trọng Khi Thiết Lập Request Trên Postman

> [!IMPORTANT]
> **LỖI PHỔ BIẾN (422 Unprocessable Entity - "field required: body"):**
> Các endpoint `POST` và `PUT` (`/api/auth/login`, `/api/users`) yêu cầu gửi dữ liệu dạng **JSON Body**, KHÔNG gửi qua Query Params.
>
> **Cách cấu hình chuẩn trong Postman:**
>
> 1. Tab **Params**: Bỏ tick / Xóa toàn bộ Query Params trên URL. URL chỉ để dạng: `{{baseUrl}}/api/auth/login`
> 2. Tab **Body**: Chọn radio **`raw`**, dropdown bên phải chọn **`JSON`** (thay vì Text).
> 3. Tab **Headers**: Kiểm tra header `Content-Type` là `application/json`.
> 4. Tab **Scripts** -> **Post-response** (hoặc **Tests** ở bản cũ): Dán script để tự động trích xuất token vào biến `authToken`.

---

## 3. Danh Sách Các Endpoint API

| Phương thức | Đường dẫn API    | Xác thực   | Mục đích                                                               |
| :------------- | :------------------- | :----------- | :------------------------------------------------------------------------ |
| `POST`       | `/api/auth/login`  | Công khai   | Đăng nhập hệ thống, cấp phát JWT Access Token                      |
| `GET`        | `/api/auth/me`     | Bearer Token | Lấy thông tin cá nhân của tài khoản đang đăng nhập             |
| `POST`       | `/api/auth/logout` | Công khai   | Đăng xuất và xóa phiên làm việc                                   |
| `GET`        | `/api/users`       | Bearer Token | Truy vấn danh sách tài khoản (phân trang, lọc vai trò, tìm kiếm) |
| `POST`       | `/api/users`       | Bearer Token | Tạo tài khoản mới (hỗ trợ giá trị mặc định tối giản)         |
| `GET`        | `/api/users/{id}`  | Bearer Token | Lấy thông tin chi tiết một tài khoản theo Snowflake ID              |
| `PUT`        | `/api/users/{id}`  | Bearer Token | Cập nhật thông tin tài khoản hoặc đặt lại mật khẩu             |
| `DELETE`     | `/api/users/{id}`  | Bearer Token | Xóa tài khoản khỏi hệ thống                                         |

---

## 4. Kịch Bản Kiểm Thử Chi Tiết (Test Cases)

### TC-01: Đăng nhập tài khoản Admin thành công (POST /api/auth/login)

* **Method**: `POST`
* **URL**: `{{baseUrl}}/api/auth/login`
* **Postman Tab Params**: Không điền param nào (Xóa hết `username`, `password` trên Params nếu có).
* **Postman Tab Body**: Chọn **`raw`** -> Chọn kiểu **`JSON`**:

  ```json
  {
    "username": "{{adminUsername}}",
    "password": "{{adminPassword}}"
  }
  ```

  *(hoặc nhập trực tiếp `"username": "admin"`, `"password": "123456"`)*
* **Postman Tab Scripts -> Post-response (hoặc Tests)**:

  ```javascript
  pm.test("Status code is 200", function () {
      pm.response.to.have.status(200);
  });

  pm.test("Lưu authToken tự động vào Environment", function () {
      var jsonData = pm.response.json();
      pm.expect(jsonData.ok).to.eql(true);
      pm.expect(jsonData.access_token).to.be.a("string");
      pm.environment.set("authToken", jsonData.access_token);
      console.log("Đã lưu authToken thành công:", jsonData.access_token);
  });
  ```
* **cURL tương đương**:

  ```bash
  curl -X POST "http://localhost:8000/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{
      "username": "admin",
      "password": "123456"
    }'
  ```
* **Kết quả kỳ vọng (`200 OK`)**:

  ```json
  {
    "ok": true,
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "user": {
      "id": "379330358447050752",
      "username": "admin",
      "full_name": "Quản Trị Viên Hệ Thống",
      "role": "admin",
      "email": "admin@vsico.com.vn",
      "zalo_user_id": "6691387223255581446",
      "zalo_info_id": "3073804738540831090",
      "tms_user_id": null,
      "forwarder_id": null,
      "is_active": true,
      "last_login_at": "2026-11-13T01:03:36",
      "created_at": "2026-11-13T01:03:25",
      "updated_at": null
    },
    "message": "Đăng nhập thành công"
  }
  ```

---

### TC-02: Đăng nhập thất bại khi sai mật khẩu (POST /api/auth/login)

* **Method**: `POST`
* **URL**: `{{baseUrl}}/api/auth/login`
* **Postman Tab Body**: `raw` -> `JSON`:

  ```json
  {
    "username": "admin",
    "password": "wrong_password"
  }
  ```
* **cURL**:

  ```bash
  curl -X POST "http://localhost:8000/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{
      "username": "admin",
      "password": "wrong_password"
    }'
  ```
* **Kết quả kỳ vọng (`401 Unauthorized`)**:

  ```json
  {
    "detail": "Tài khoản hoặc mật khẩu không chính xác."
  }
  ```

---

### TC-03: Lấy thông tin cá nhân tài khoản đang đăng nhập (GET /api/auth/me)

* **Method**: `GET`
* **URL**: `{{baseUrl}}/api/auth/me`
* **Postman Tab Authorization**: Chọn Type là **`Bearer Token`** -> Token điền: `{{authToken}}`.
  *(Hoặc ở tab Headers: thêm key `Authorization` với value `Bearer {{authToken}}`)*
* **cURL**:

  ```bash
  curl -X GET "http://localhost:8000/api/auth/me" \
    -H "Authorization: Bearer <dán_access_token_vào_đây>"
  ```
* **Kết quả kỳ vọng (`200 OK`)**:

  ```json
  {
    "id": "379330358447050752",
    "username": "admin",
    "full_name": "Quản Trị Viên Hệ Thống",
    "role": "admin",
    "email": "admin@vsico.com.vn",
    "zalo_user_id": "6691387223255581446",
    "zalo_info_id": "3073804738540831090",
    "tms_user_id": null,
    "forwarder_id": null,
    "is_active": true,
    "last_login_at": "2026-11-13T01:03:36",
    "created_at": "2026-11-13T01:03:25",
    "updated_at": null
  }
  ```

---

### TC-04: Tạo mới tài khoản với thông tin tối giản (POST /api/users)

Tạo người dùng mới chỉ cần cung cấp trường `username`. Hệ thống tự động áp dụng các giá trị mặc định:

- `password`: `123456`
- `zalo_user_id`: `6691387223255581446`
- `zalo_info_id`: `3073804738540831090`
- `role`: `dhvt`
- `full_name`: tự động điền theo `username`
- `is_active`: `true`

* **Method**: `POST`
* **URL**: `{{baseUrl}}/api/users`
* **Postman Tab Authorization**: `Bearer Token` -> `{{authToken}}`
* **Postman Tab Body**: `raw` -> `JSON`:

  ```json
  {
    "username": "dhvt_haiphong_01"
  }
  ```
* **Postman Tab Scripts -> Post-response (hoặc Tests)**:

  ```javascript
  pm.test("Status code is 201 Created", function () {
      pm.response.to.have.status(201);
  });
  pm.test("Lưu createdUserId tự động", function () {
      var jsonData = pm.response.json();
      pm.expect(jsonData.ok).to.eql(true);
      pm.expect(jsonData.data.role).to.eql("dhvt");
      pm.environment.set("createdUserId", jsonData.data.id);
  });
  ```
* **cURL**:

  ```bash
  curl -X POST "http://localhost:8000/api/users" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer <dán_access_token_vào_đây>" \
    -d '{
      "username": "dhvt_haiphong_01"
    }'
  ```
* **Kết quả kỳ vọng (`201 Created`)**:

  ```json
  {
    "ok": true,
    "data": {
      "id": "379330403493875712",
      "username": "dhvt_haiphong_01",
      "full_name": "dhvt_haiphong_01",
      "role": "dhvt",
      "email": null,
      "zalo_user_id": "6691387223255581446",
      "zalo_info_id": "3073804738540831090",
      "tms_user_id": null,
      "forwarder_id": null,
      "is_active": true,
      "last_login_at": null,
      "created_at": "2026-11-13T01:03:36",
      "updated_at": null
    },
    "message": "Tạo mới tài khoản thành công."
  }
  ```

---

### TC-05: Đăng nhập bằng tài khoản mới vừa tạo với mật khẩu mặc định (POST /api/auth/login)

* **Method**: `POST`
* **URL**: `{{baseUrl}}/api/auth/login`
* **Postman Tab Body**: `raw` -> `JSON`:

  ```json
  {
    "username": "dhvt_haiphong_01",
    "password": "123456"
  }
  ```
* **Kết quả kỳ vọng (`200 OK`)**: Đăng nhập thành công và trả về access token mới của nhân viên điều hành.

---

### TC-06: Ngăn chặn tạo trùng tên đăng nhập (POST /api/users)

* **Method**: `POST`
* **URL**: `{{baseUrl}}/api/users`
* **Postman Tab Authorization**: `Bearer Token` -> `{{authToken}}`
* **Postman Tab Body**: `raw` -> `JSON`:

  ```json
  {
    "username": "dhvt_haiphong_01"
  }
  ```
* **Kết quả kỳ vọng (`400 Bad Request`)**:

  ```json
  {
    "detail": "Tên đăng nhập 'dhvt_haiphong_01' đã tồn tại trong hệ thống."
  }
  ```

---

### TC-07: Truy vấn danh sách tài khoản phân trang (GET /api/users)

* **Method**: `GET`
* **URL**: `{{baseUrl}}/api/users?page=1&page_size=20&role=dhvt`
* **Postman Tab Authorization**: `Bearer Token` -> `{{authToken}}`
* **Postman Tab Params**:

  - `page`: `1`
  - `page_size`: `20`
  - `role`: `dhvt` (hoặc để trống để lấy tất cả)
* **Kết quả kỳ vọng (`200 OK`)**:

  ```json
  {
    "ok": true,
    "total": 1,
    "page": 1,
    "page_size": 20,
    "items": [
      {
        "id": "379330403493875712",
        "username": "dhvt_haiphong_01",
        "full_name": "dhvt_haiphong_01",
        "role": "dhvt",
        "email": null,
        "zalo_user_id": "6691387223255581446",
        "zalo_info_id": "3073804738540831090",
        "tms_user_id": null,
        "forwarder_id": null,
        "is_active": true,
        "last_login_at": "2026-11-13T01:04:00",
        "created_at": "2026-11-13T01:03:36",
        "updated_at": null
      }
    ]
  }
  ```

---

### TC-08: Xem chi tiết tài khoản theo Snowflake ID (GET /api/users/)

* **Method**: `GET`
* **URL**: `{{baseUrl}}/api/users/{{createdUserId}}`
* **Postman Tab Authorization**: `Bearer Token` -> `{{authToken}}`
* **Kết quả kỳ vọng (`200 OK`)**: Trả về đúng thông tin tài khoản có ID tương ứng.

---

### TC-09: Cập nhật thông tin và đổi mật khẩu tài khoản (PUT /api/users/)

* **Method**: `PUT`
* **URL**: `{{baseUrl}}/api/users/{{createdUserId}}`
* **Postman Tab Authorization**: `Bearer Token` -> `{{authToken}}`
* **Postman Tab Body**: `raw` -> `JSON`:

  ```json
  {
    "full_name": "Nguyễn Văn Điều Hành",
    "email": "dhvt.hp01@vsico.com.vn",
    "password": "new_password_2026"
  }
  ```
* **Kết quả kỳ vọng (`200 OK`)**:

  ```json
  {
    "ok": true,
    "data": {
      "id": "379330403493875712",
      "username": "dhvt_haiphong_01",
      "full_name": "Nguyễn Văn Điều Hành",
      "role": "dhvt",
      "email": "dhvt.hp01@vsico.com.vn",
      "zalo_user_id": "6691387223255581446",
      "zalo_info_id": "3073804738540831090",
      "tms_user_id": null,
      "forwarder_id": null,
      "is_active": true,
      "last_login_at": "2026-11-13T01:04:00",
      "created_at": "2026-11-13T01:03:36",
      "updated_at": "2026-11-13T01:05:00"
    },
    "message": "Cập nhật tài khoản thành công."
  }
  ```

---

### TC-10: Xóa tài khoản khỏi hệ thống (DELETE /api/users/)

* **Method**: `DELETE`
* **URL**: `{{baseUrl}}/api/users/{{createdUserId}}`
* **Postman Tab Authorization**: `Bearer Token` -> `{{authToken}}`
* **Kết quả kỳ vọng (`200 OK`)**:

  ```json
  {
    "ok": true,
    "message": "Đã xóa tài khoản 'dhvt_haiphong_01' (ID: 379330403493875712) thành công."
  }
  ```

---

### TC-11: Xác nhận tài khoản đã bị xóa (GET /api/users/)

* **Method**: `GET`
* **URL**: `{{baseUrl}}/api/users/{{createdUserId}}`
* **Postman Tab Authorization**: `Bearer Token` -> `{{authToken}}`
* **Kết quả kỳ vọng (`404 Not Found`)**:

  ```json
  {
    "detail": "Không tìm thấy tài khoản có ID 379330403493875712."
  }
  ```

---

### TC-12: Đăng xuất khỏi hệ thống (POST /api/auth/logout)

* **Method**: `POST`
* **URL**: `{{baseUrl}}/api/auth/logout`
* **Kết quả kỳ vọng (`200 OK`)**:

  ```json
  {
    "ok": true,
    "message": "Đăng xuất thành công"
  }
  ```
