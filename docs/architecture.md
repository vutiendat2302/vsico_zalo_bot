# KIẾN TRÚC HỆ THỐNG ZALO GMF BOT - VSICO TMS (DOCS/ARCHITECTURE.MD)

## 1. Nguyên Tắc Phân Tầng (Layered Clean Architecture)

Hệ thống được thiết kế theo nguyên lý phụ thuộc một chiều từ ngoài vào trong:

```
[API Layer] (FastAPI / HTTP Server)
    │
    ▼
[Ingestion Layer] (Payload Normalization, Filters, Deduplication)
    │
    ▼
[Messaging & Router Layer] (Context Resolver, Preprocessing, Intent Classifier)
    │
    ▼
[Handlers / Use Case Layer] (CreateTrip, UpdateDriver, CancelTrip, Supplement)
    │
    ▼
[Domain Core Layer] (Pure Business Models, ISO 6346 Mod 11, Shipping Matcher)
    ▲
    │
[Infrastructure Layer] (Zalo Client, LLM Client, Repositories, Queue)
```

## 2. Quy Tắc Bất Biến (Invariants)
1. **Lõi Domain thuần khiết**: `domain/` không import bất kỳ thư viện HTTP, Webhook, Zalo hay DB nào. Mọi phụ thuộc ngoại vi đều thông qua Abstract Interface (Dependency Inversion).
2. **Payload Zalo độc lập**: Cấu trúc payload của Zalo chỉ tồn tại trong `api/schemas/zalo.py` và `ingestion/`. Toàn bộ hệ thống bên trong chỉ làm việc với đối tượng `InboundMessage`.
3. **Idempotency tuyệt đối**: Mọi tin nhắn đều được deduplicate theo `msg_id` tại cửa ngõ Ingestion. Xử lý 2 lần luôn cho kết quả an toàn giống như 1 lần.
4. **Không truyền dict trần**: Mọi dữ liệu trao đổi giữa các tầng đều dùng `dataclass` có type-hint rõ ràng.
