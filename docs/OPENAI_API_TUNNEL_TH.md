# ใช้ Endeavor Hands ผ่าน OpenAI API + Secure MCP Tunnel

วิธีนี้ใช้ **Responses API** เป็นสมองและใช้ Secure MCP Tunnel เป็นทางเชื่อมไปยัง
Endeavor Hands บน Mac จึงไม่ต้องเปิดพอร์ตจากอินเทอร์เน็ตเข้ามาที่เครื่อง

> ค่าโมเดลคิดตามราคา OpenAI API แยกจากค่าสมาชิก ChatGPT ส่วน MCP tool call
> ไม่มีค่าธรรมเนียมต่อครั้งเพิ่ม แต่ token ที่ใช้โหลด tool schema, arguments,
> ผลลัพธ์ และคำตอบยังนับเป็นการใช้ API

## สิ่งที่ต้องมี

1. Mac Apple Silicon และ Python 3.11
2. OpenAI Platform organization ที่มีสิทธิ์ Tunnels **Read + Manage + Use**
3. Tunnel ID รูปแบบ `tunnel_...`
4. runtime API key สำหรับ `tunnel-client` ที่มี Tunnels **Read + Use**
5. OpenAI API key สำหรับ Responses API พร้อม billing/usage limit ที่เหมาะสม

runtime API key กับ Responses API key เป็นคนละหน้าที่ และ launcher เก็บแยกกัน
ใน macOS Keychain ห้ามส่ง key ใดๆ เข้าแชตหรือ commit ลง Git

## 1. ติดตั้ง branch ทดสอบ

ใช้โฟลเดอร์ใหม่เพื่อไม่ทับ repo เดิม:

```bash
cd ~/Desktop
git clone --branch feat/aegis-protected-endeavor \
  https://github.com/namo1997/Endeavor_Hands.git Endeavor_Hands_AEGIS_Test
cd Endeavor_Hands_AEGIS_Test
bash install_library/install.sh
```

ถ้าไม่มี `python3.11` ให้ติดตั้งก่อน เช่น `brew install python@3.11`

## 2. สร้างและเปิด Secure MCP Tunnel

สร้าง Tunnel ใน OpenAI Platform แล้วดาวน์โหลด `tunnel-client` รุ่น Darwin
arm64 มาวางเป็น `bin/tunnel-client` จากนั้น:

```bash
chmod +x bin/tunnel-client start_tunnel.sh scripts/*.command
./start_tunnel.sh
```

ตัวตั้งค่าจะถาม Tunnel ID และ runtime API key โดยไม่แสดง key บนหน้าจอ เมื่อ
`doctor` ผ่าน ให้เปิด Terminal นี้ค้างไว้ ตรวจสถานะได้ที่:

```text
http://127.0.0.1:8765/ui
http://127.0.0.1:8765/readyz
```

ครั้งถัดไปใช้ `scripts/start_tunnel.command` ได้

## 3. เปิด API chat

เปิด Terminal อีกหน้าต่างแล้วดับเบิลคลิก `scripts/start_api_chat.command` หรือรัน:

```bash
./scripts/start_api_chat.command
```

ครั้งแรก launcher จะถาม Responses API key แบบซ่อน และถาม Tunnel ID จากนั้นเก็บ
ทั้งสองค่าแยกกันใน macOS Keychain ไม่เขียนลง source, `.env`, profile หรือ log

ค่าเริ่มต้นใช้ `gpt-5.6` เปลี่ยนได้เฉพาะ process ปัจจุบัน เช่น:

```bash
OPENAI_MODEL=โมเดลที่บัญชีคุณใช้ได้ ./scripts/start_api_chat.command
```

## 4. ทดสอบแบบไม่แก้ไฟล์

เริ่มด้วยคำสั่งอ่านอย่างเดียว:

```text
ใช้ Endeavor Hands อ่านรายชื่อไฟล์ระดับแรกใต้ ~/Desktop เท่านั้น ห้ามแก้ไข
```

API client จะแสดงชื่อ tool และ arguments แล้วถาม `Approve this tool call?`
ทุกครั้ง กด `y` เฉพาะเมื่อชื่อและ arguments ตรงกับสิ่งที่ตั้งใจ หลังจบแต่ละ
ข้อความจะแสดงจำนวน input/output/total tokens ของรอบนั้นเพื่อช่วยตรวจการใช้งาน

## 5. ทดสอบ Working Envelope

สร้างโฟลเดอร์ทดสอบเองก่อน:

```bash
mkdir -p ~/Desktop/aegis-smoke-test
```

จากนั้นพิมพ์ใน API chat:

```text
ฉันอนุญาตงานสร้างไฟล์ hello.txt ภายใต้
/Users/ชื่อผู้ใช้/Desktop/aegis-smoke-test เท่านั้น เป็นเวลา 15 นาที
ให้สิทธิ์ file_write เท่านั้น เขียนคำว่า hello แล้วอ่านกลับมาตรวจสอบ
ห้ามใช้ shell, Python, Git หรือ computer และ revoke เมื่อเสร็จ
```

ใช้ absolute path จริงจากคำสั่ง `pwd` แทน `/Users/ชื่อผู้ใช้/...`

ผลที่ต้องได้:

- โมเดลเรียก `aegis_start_session` ด้วย root และ capability ที่อนุญาต
- สร้างไฟล์ภายใน root ได้หลังคุณอนุมัติ tool call
- การเขียนนอก root ถูกปฏิเสธ
- session ถูก revoke หลังงานจบ

## ความเป็นส่วนตัวและการคิดค่าใช้จ่าย

API chat ใช้ `previous_response_id` และ Responses API storage เพื่อรักษาบริบท
ของบทสนทนา Prompt, tool arguments, tool results และข้อมูลที่โมเดลต้องใช้จึงถูก
ส่งไปประมวลผลโดย OpenAI อย่าสั่งให้อ่านไฟล์ลับหรือข้อมูลที่ไม่ต้องการส่งไปยัง
API และตั้ง Usage limit ใน OpenAI Platform ก่อนทดลองใช้งานจริง

คำสั่ง `/new` เริ่มบทสนทนาใหม่ และ `/quit` ปิด client แต่ไม่ได้ลบ Response ที่
OpenAI จัดเก็บไว้
