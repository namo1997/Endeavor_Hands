# Security policy

**English** | [ภาษาไทย](#ภาษาไทย)

Endeavor Hands gives an MCP client (ChatGPT web, via the OpenAI
Secure MCP Tunnel, or any other MCP client) real capability on this Mac:
shell commands, Python execution, file read/write/edit, and guarded
screen/mouse/keyboard control. Do not report suspected vulnerabilities in a
public issue.

Send a private report to **champoomwat@gmail.com** with:

- a clear description and affected version/commit;
- reproducible steps or a minimal proof of concept;
- the potential impact; and
- any suggested mitigation, if available.

Please do not include real credentials, personal files, or destructive
payloads in the report. We will acknowledge a valid report, investigate it
privately, and coordinate disclosure after a fix is available.

## Security boundaries

- **Tunnel is outbound-only.** The OpenAI Secure MCP Tunnel is an HTTPS
  connection this Mac makes out to OpenAI; nothing needs to be exposed on an
  inbound port. The MCP server itself talks stdio only, to the local
  `tunnel-client` process — it does not listen on any network port.
- **Every effectful call requires an AEGIS Working Envelope.** The exact
  high-entropy `session_id + working_envelope_id` pair selects an immutable
  canonical root, capability set, ACTIVE state, expiry, and revocation state.
  The request-local binding is a `ContextVar`, not a process-global current
  workspace. Cross-session identifier, grant, process, and mutation authority
  is denied.
- **Canonical paths are contained in the immutable root.** Existing symlinks
  and the nearest existing ancestor of a new path are resolved before the
  decision. `/`, the whole home directory, system roots, credential paths, and
  Endeavor/AEGIS internal state are not mutation roots or targets.
- **Shell/Python use a strict write allow-list.** An AEGIS-bound
  `sandbox-exec` profile denies every filesystem write before allowing only
  the immutable root and `/private/tmp`. It denies unlink globally. Guarded
  Git can receive a narrow unlink exception for its selected `.git` metadata,
  never source files. This covers shell redirection and child processes rather
  than relying on command-text keyword matching.
- **Direct existing-file writes use optimistic concurrency.** `edit` and
  `write_file(overwrite=true)` require the SHA-256 returned by
  `aegis_file_state`. A stale value returns
  `CONCURRENT_MODIFICATION_DETECTED` before replacement.
- **Existing-file modification also retains a conversation consent gate.** The first `edit`
  call, or `write_file` with `overwrite=true` on a file that already
  exists, targeting a given top-level workspace folder fails with
  `[permission_required]` and a one-time nonce until the user explicitly
  approves that folder in the same conversation
  (`tools/_edit_grants.py`). This is a workflow gate reinforced by the
  model's own instructions, not a cryptographic guarantee — treat it as
  friction against an accidental or careless edit, not as a hard boundary
  against a model that has been deliberately jailbroken. Pending/granted
  nonces are scoped to the exact AEGIS pair.
- **Background jobs and nested MCP registrations are owner-isolated.** Jobs
  can only be listed/polled/killed by their exact envelope pair and are stopped
  on revocation. Dynamic MCP registrations are stored per envelope in
  protected internal state; local stdio servers use direct argv and the same
  strict sandbox.
- **`computer` requires macOS Accessibility permission** and refuses to
  interact with password/secure-text fields. It also refuses actions whose
  target text reads as delete/remove-related, independent of the
  file-deletion guard above.
- **Read plane remains separate.** `read_file` is read-only and can inspect
  paths outside a mutation envelope, except fixed protected system/credential
  and internal-state paths. An absolute path should be used when reading
  outside the default workspace.
- **A write envelope is not a confidentiality or network sandbox.** `bash` and
  `python_exec` retain outbound network access and can read most paths outside
  the root except the protected credential/internal paths. The `process_exec`
  capability also permits writes anywhere inside the selected root without the
  direct-edit consent nonce. Use a narrow root, least capabilities, and do not
  run untrusted code when those authorities are unacceptable.
- **Some effects are outside filesystem containment.** `computer_control` can
  affect visible applications, and a remote nested MCP can perform whatever
  effects its own server exposes. Revocation blocks later calls and stops owned
  background jobs, but it cannot roll back completed effects or reliably cancel
  a synchronous call that was already running when revocation occurred.

The production grant source is ChatGPT-trusted user intent: ChatGPT must call
`aegis_start_session` only after the owner authorizes the task and exact root
in the conversation. There is no second cryptographic human-presence proof.
These are strong local single-owner controls, not a multi-user OS-account or
multi-tenant security boundary. `computer_control` can affect visible apps
outside the filesystem root, subject to its secure-field/destructive guards.

---

# ภาษาไทย

[English](#security-policy)

Endeavor Hands ให้ MCP client (ChatGPT web ผ่าน OpenAI Secure MCP
Tunnel หรือ MCP client อื่นใด) มีความสามารถจริงบนเครื่อง Mac นี้: รันคำสั่ง
shell, รัน Python, อ่าน/เขียน/แก้ไฟล์, และควบคุมหน้าจอ/เมาส์/คีย์บอร์ดแบบ
มีการ์ด อย่ารายงานช่องโหว่ที่สงสัยผ่าน public issue

ส่งรายงานแบบส่วนตัวไปที่ **champoomwat@gmail.com** พร้อม:

- คำอธิบายที่ชัดเจนและ version/commit ที่ได้รับผลกระทบ
- ขั้นตอนทำซ้ำได้ หรือ proof of concept แบบย่อ
- ผลกระทบที่อาจเกิดขึ้น
- ข้อเสนอแนะการแก้ไข (ถ้ามี)

โปรดอย่าใส่ credential จริง, ไฟล์ส่วนตัว, หรือ payload ที่ทำลายระบบใน
รายงาน เราจะตอบรับรายงานที่ถูกต้อง สืบสวนแบบส่วนตัว และประสานงานเปิดเผย
หลังมีการแก้ไขแล้ว

## ขอบเขตความปลอดภัย

- **Tunnel เป็นขาออกเท่านั้น** OpenAI Secure MCP Tunnel คือการเชื่อมต่อ
  HTTPS ที่ Mac เครื่องนี้เชื่อมออกไปหา OpenAI เอง ไม่ต้องเปิดอะไรให้
  อินเทอร์เน็ตเข้าถึงเลย ตัว MCP server เองคุยผ่าน stdio กับ
  `tunnel-client` ที่รันอยู่ในเครื่องเท่านั้น — ไม่ listen พอร์ตเครือข่าย
  ใดๆ
- **ทุก effectful call ต้องมี AEGIS Working Envelope** คู่ high-entropy
  `session_id + working_envelope_id` ต้องตรงกัน และเลือก canonical root,
  capability, สถานะ ACTIVE, วันหมดอายุ และสถานะเพิกถอนที่แก้ไม่ได้ การ bind
  ใช้ `ContextVar` ต่อ request ไม่ใช้ global current workspace จึงไม่รับสิทธิ์
  ข้ามแชต
- **ตรวจ canonical path และ symlink ก่อนอนุญาต** root เป็น immutable และห้าม
  `/`, home ทั้งก้อน, system root, credential path และ internal state ของระบบ
- **Shell/Python ใช้ strict write allow-list** `sandbox-exec` deny การเขียนทั้งหมด
  แล้ว allow เฉพาะ root กับ `/private/tmp`; deny unlink ทั้งหมด ส่วน guarded Git
  ได้ข้อยกเว้นเฉพาะ metadata ที่เลือกไว้ ไม่รวม source file
- **การแก้/แทนที่ไฟล์เดิมตรวจ optimistic concurrency** ต้องส่ง SHA-256 จาก
  `aegis_file_state`; ค่า stale จะคืน `CONCURRENT_MODIFICATION_DETECTED`
- **การแก้ไฟล์เดิมต้องได้รับอนุญาตในระดับ session** การเรียก `edit` หรือ
  `write_file` แบบ `overwrite=true` บนไฟล์ที่มีอยู่แล้ว ครั้งแรกที่แตะ
  โฟลเดอร์ระดับบนสุดในแต่ละ session จะ fail ด้วย `[permission_required]`
  พร้อมรหัสครั้งเดียว จนกว่าผู้ใช้จะอนุญาตโฟลเดอร์นั้นในบทสนทนาเดียวกัน
  (`tools/_edit_grants.py`) นี่คือ workflow gate ที่เสริมด้วยคำสั่งของ
  โมเดลเอง ไม่ใช่การรับประกันทางการเข้ารหัส — ให้มองว่าเป็น friction
  ป้องกันการแก้ไขโดยไม่ได้ตั้งใจหรือประมาท ไม่ใช่ขอบเขตที่แข็งแกร่งต่อ
  โมเดลที่ถูก jailbreak โดยเจตนา และ nonce จะผูกกับคู่ AEGIS นั้นเท่านั้น
- **Background job และ nested MCP แยกเจ้าของตามคู่ envelope** คู่หนึ่งไม่สามารถ
  list/poll/kill job ของอีกคู่ และตอน revoke จะหยุด job ที่เป็นเจ้าของ
- **`computer` ต้องมีสิทธิ์ macOS Accessibility** และปฏิเสธการโต้ตอบกับ
  ช่องรหัสผ่าน/secure-text นอกจากนี้ยังปฏิเสธ action ที่ target text อ่าน
  ได้ว่าเกี่ยวกับการลบ/ทำลาย แยกต่างหากจาก guard การลบไฟล์ด้านบน
- **Read Plane แยกจาก Mutation Plane** `read_file` อ่านนอก envelope ได้แบบ
  read-only ยกเว้น system/credential/internal path ที่คุ้มครองไว้
- **Write envelope ไม่ใช่ confidentiality/network sandbox** `bash` และ
  `python_exec` ยังออก network ได้และอ่าน path ส่วนใหญ่นอก root ได้ ยกเว้น
  credential/internal path ที่ป้องกันไว้ และ `process_exec` เขียนได้ทุกจุดใน
  root โดยไม่ผ่าน nonce ของ direct edit จึงต้องเลือก root แคบและให้ capability
  เท่าที่จำเป็น
- **บาง effect อยู่นอกขอบเขต filesystem** `computer_control` กระทบแอปที่มองเห็น
  ได้ และ remote nested MCP ทำ effect ตามที่ server ปลายทางเปิดไว้ การ revoke
  ปิด call ถัดไปและหยุด background job ที่เป็นเจ้าของ แต่ย้อนผลที่เสร็จแล้วหรือ
  รับประกันการยกเลิก synchronous call ที่เริ่มไปแล้วไม่ได้

แหล่ง authorization ใน production คือ CHATGPT-TRUSTED USER INTENT: ChatGPT
ต้องเรียก `aegis_start_session` หลังเจ้าของอนุญาตงานและ root ที่แน่นอนใน
บทสนทนาแล้วเท่านั้น ไม่มีหลักฐาน human-presence แบบเข้ารหัสจาก UI ที่สอง
ระบบนี้เป็นขอบเขตสำหรับเครื่องเดียว/เจ้าของเดียว ไม่ใช่ OS account sandbox
หรือ multi-tenant boundary และ `computer_control` ยังส่งผลต่อแอปที่มองเห็นได้
นอก filesystem root ภายใต้ secure-field/destructive guard เดิม
