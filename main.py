import os
import json
import re
import base64
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, ImageMessage, TextMessage, AudioMessage, TextSendMessage, FlexSendMessage
)

app = Flask(__name__)

# ==================== CONFIG CREDENTIALS ====================
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get(
    "LINE_CHANNEL_ACCESS_TOKEN", 
    "baSWvsupfACGN0GFkgOGgH0UIvLrQO51yZZCBDDTUWJi8Ng29Xaj1kF3DjiYm3LdOUxe7q8m+EvPfarjixeL6GBc41sAo4KzBtvMC+t2RPZXbuuzNfizb4pKSVOZDllHaOytzNlzFW4Jl4VlQOe69AdB04t89/1O/w1cDnyilFU="
).strip()

LINE_CHANNEL_SECRET = os.environ.get(
    "LINE_CHANNEL_SECRET", 
    "490d4f5e36a60913923f3bd1c8768a15"
).strip()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

CAREGIVER_LINE_ID = os.environ.get(
    "CAREGIVER_LINE_ID", 
    "U30245f201766077aac8b18bd15db6377"
).strip()
# ============================================================

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

def call_gemini_api(prompt, mime_type=None, data_bytes=None):
    """ส่งคำสั่งตรงไปยัง Gemini REST API รองรับรหัสคีย์ทุกรูปแบบ"""
    models = ["gemini-1.5-flash", "gemini-2.0-flash"]
    
    parts = [{"text": prompt}]
    if data_bytes and mime_type:
        b64_data = base64.b64encode(data_bytes).decode('utf-8')
        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": b64_data
            }
        })
    payload = {"contents": [{"parts": parts}]}

    for model_name in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        headers = {"Content-Type": "application/json"}
        
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=20)
            if res.status_code == 200:
                res_json = res.json()
                text = res_json.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text")
                if text:
                    return text
            print(f"[Gemini Error] Model: {model_name} | Code: {res.status_code} | Resp: {res.text}")
        except Exception as e:
            print(f"[Gemini Exception]: {e}")

    return None

def get_sender_name(event):
    """ดึงชื่อผู้ส่งข้อความ"""
    try:
        user_id = event.source.user_id
        if event.source.type == 'group':
            group_id = event.source.group_id
            profile = line_bot_api.get_group_member_profile(group_id, user_id)
        else:
            profile = line_bot_api.get_profile(user_id)
        return profile.display_name
    except Exception:
        return "สมาชิก"

def analyze_bp(sys_val, dia_val):
    if sys_val >= 180 or dia_val >= 120:
        return (
            "🚨 เตือนภัยอันตราย: ความดันสูงระดับวิกฤต!\n\n"
            "‼️ สิ่งที่ต้องทำทันที:\n"
            "1. ให้นั่งพักสงบๆ ทันที 5-10 นาที แล้วทำการวัดซ้ำอีกครั้ง\n"
            "2. หากมียาฉุกเฉิน ให้รับประทานทันทีตามคำแนะนำของแพทย์\n"
            "3. ⚠️ หากค่ายังไม่ลด หรือมีอาการ แน่นหน้าอก หายใจไม่สะดวก แขนขาอ่อนแรง ปากเบี้ยว ให้รีบไปโรงพยาบาลหรือโทร 1669 ทันที!"
        )
    elif sys_val >= 140 or dia_val >= 90:
        return (
            "🔴 ผลตรวจ: ความดันสูงเกินเกณฑ์มาตรฐาน (ระดับ 2)\n\n"
            "💡 ข้อควรปฏิบัติอย่างเคร่งครัด:\n"
            "• เรื่องยา: ทานยาตามแพทย์สั่งอย่างเคร่งครัด 🚫 ห้ามหยุดยาหรือลดยาเองเด็ดขาด\n"
            "• กิจกรรม: งดการยกของหนัก หรือการออกแรงเกร็งตัวมากเกินไป\n"
            "• สังเกตอาการ: หากมีอาการ ปวดท้ายทอย ตาพร่ามัว หรือเวียนศีรษะ ให้รีบนั่งพักทันที"
        )
    elif sys_val >= 130 or dia_val >= 80:
        return (
            "⚠️ ผลตรวจ: ความดันเริ่มสูงกว่าปกติ (ระดับ 1)\n\n"
            "💡 ข้อควรปฏิบัติสำคัญ:\n"
            "• งดเค็มเด็ดขาด: งดผงชูรส น้ำปลา อาหารหมักดอง และอาหารกระป๋อง\n"
            "• เรื่องยา: หากมียาประจำตัว ต้องทานให้ตรงเวลา\n"
            "• การติดตาม: วัดความดันซ้ำสัปดาห์ละ 2-3 ครั้ง และบันทึกไว้ให้คุณหมอดู"
        )
    elif sys_val >= 120 and dia_val < 80:
        return (
            "⚠️ ผลตรวจ: ความดันเริ่มสูงกว่าปกติเล็กน้อย\n\n"
            "💡 ข้อควรปฏิบัติสำคัญ:\n"
            "• งดเค็มเด็ดขาด: งดผงชูรส น้ำปลา อาหารหมักดอง และอาหารกระป๋อง\n"
            "• เรื่องยา: หากมียาประจำตัว ต้องทานให้ตรงเวลา\n"
            "• การติดตาม: วัดความดันซ้ำสัปดาห์ละ 2-3 ครั้ง และบันทึกไว้ให้คุณหมอดู"
        )
    elif sys_val < 90 or dia_val < 60:
        return (
            "🔵 ผลตรวจ: ความดันต่ำกว่าเกณฑ์ปกติ\n\n"
            "💡 คำแนะนำดูแลตัวเอง:\n"
            "• การลุกนั่ง: ค่อยๆ ลุกขึ้นช้าๆ ป้องกันอาการหน้ามืดเวียนศีรษะ\n"
            "• การดูแล: ดื่มน้ำเปล่าให้เพียงพอ วันละ 8-10 แก้ว"
        )
    else:
        return (
            "🩺 ผลตรวจ: ค่าความดันอยู่ในเกณฑ์ปกติ\n\n"
            "💡 คำแนะนำดูแลตัวเอง:\n"
            "• อาหาร: เน้นทานผักสด เลี่ยงอาหารรสจัด หวาน-มัน-เค็ม\n"
            "• ออกกำลังกาย: เดินหรือขยับร่างกาย อย่างน้อยวันละ 30 นาที\n"
            "• การดูแล: ดื่มน้ำเปล่าให้เพียงพอ และพักผ่อนให้ครบ 7-8 ชั่วโมง"
        )

def analyze_sugar(sugar_val):
    if sugar_val < 70:
        return (
            "🔵 ผลตรวจ: น้ำตาลในเลือดต่ำกว่าปกติ\n\n"
            "💡 ข้อควรปฏิบัติทันที:\n"
            "• การแก้ภาวะน้ำตาลตก: ให้รับประทานลูกอม หรือดื่มน้ำหวาน 1 แก้วทันที\n"
            "• สังเกตอาการ: หากมีอาการ มือสั่น เหงื่อออก ใจสั่น หรือเวียนศีรษะ ให้นั่งพักทันที"
        )
    elif 70 <= sugar_val <= 99:
        return (
            "🩺 ผลตรวจ: ระดับน้ำตาลในเลือดปกติ (งดอาหาร 8 ชม.)\n\n"
            "💡 คำแนะนำดูแลตัวเอง:\n"
            "• อาหาร: เลือกทาน ข้าวกล้อง ข้าวไรซ์เบอร์รี่ แทนข้าวขาว\n"
            "• ของหวาน: งดน้ำหวาน ขนมหวาน และผลไม้รสหวานจัด เช่น ทุเรียน ลำไย"
        )
    elif 100 <= sugar_val <= 125:
        return (
            "⚠️ ผลตรวจ: เสี่ยงภาวะเบาหวาน (Pre-diabetes)\n\n"
            "💡 ข้อควรปฏิบัติสำคัญ:\n"
            "• งดเครื่องดื่ม: งดชาชง กาแฟเย็น น้ำอัดลม น้ำผลไม้พร้อมดื่ม\n"
            "• หลังทานอาหาร: เดินออกกำลังกายเบาๆ 15 นาที หลังมื้ออาหาร ช่วยลดน้ำตาลได้ดีมาก\n"
            "• การคัดกรอง: ควรตรวจติดตามค่าน้ำตาลซ้ำทุกๆ 3 เดือน"
        )
    elif 126 <= sugar_val < 200:
        return (
            "🔴 ผลตรวจ: ระดับน้ำตาลสูง (เข้าข่ายเบาหวาน)\n\n"
            "💡 ข้อควรปฏิบัติอย่างเคร่งครัด:\n"
            "• เรื่องยา: ทานยาหรือฉีดยาเบาหวานให้ตรงเวลา 🚫 ห้ามลืมยาเด็ดขาด\n"
            "• การดูแลเท้า: สวมรองเท้านุ่มๆ เสมอ 🚫 ห้ามเดินเท้าเปล่า เพื่อป้องกันการเกิดแผล\n"
            "• ข้อควรระวัง: หากมีอาการ เหงื่อออก ใจสั่น มือสั่น (น้ำตาลตก) ให้รีบรับประทานลูกอมหรือน้ำหวานทันที 1 แก้ว"
        )
    else:
        return (
            "🚨 เตือนภัย: ระดับน้ำตาลในเลือดสูงมากผิดปกติ!\n\n"
            "‼️ สิ่งที่ต้องทำทันที:\n"
            "1. จิบน้ำเปล่าบ่อยๆ เพื่อช่วยขับน้ำตาลส่วนเกินออกทางปัสสาวะ\n"
            "2. งดแป้ง ข้าว ขนม และน้ำหวานทุกชนิดทันที\n"
            "3. ตรวจสอบว่าลืมทานยาหรือฉีดยามื้อล่าสุดหรือไม่\n"
            "4. ⚠️ หากมีอาการ คอแห้งกระหายน้ำจัด ปัสสาวะบ่อย อ่อนเพลียมาก หรือคลื่นไส้อาเจียน ควรรีบไปพบแพทย์ทันที"
        )

def get_fallback_flex_message():
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "⚠️ อ่านค่าจากรูปภาพไม่สำเร็จ", "weight": "bold", "color": "#D93025", "size": "md"},
                {"type": "text", "text": "รูปถ่ายมีเงาสะท้อนหรือมองเห็นตัวเลขไม่ชัดเจน กรุณากดปุ่มเพื่อกรอกตัวเลขด้วยตนเองครับ", "wrap": True, "color": "#666666", "size": "xs", "margin": "md"}
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#1DB446", "height": "sm", "action": {"type": "message", "label": "กรอกค่าความดัน", "text": "พิมพ์ค่าความดัน"}},
                {"type": "button", "style": "secondary", "height": "sm", "action": {"type": "message", "label": "กรอกค่าน้ำตาล", "text": "พิมพ์ค่าน้ำตาล"}}
            ]
        }
    }

def notify_caregiver(title, detail_text, sender_name=""):
    alert_msg = f"⚠️ แจ้งเตือนผู้ดูแล: {title}\nผู้ส่ง: คุณ{sender_name}\n{detail_text}\nกรุณาติดต่อสอบถามอาการ"
    try:
        line_bot_api.push_message(CAREGIVER_LINE_ID, TextSendMessage(text=alert_msg))
    except Exception as e:
        print(f"Error pushing to caregiver: {e}")

@app.route("/", methods=['GET'])
def index():
    return "LINE Health Monitor Bot is running!", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    reply_token = event.reply_token
    raw_user_text = event.message.text.strip()
    sender_name = get_sender_name(event)
    
    if raw_user_text == "พิมพ์ค่าความดัน":
        msg = f"คุณ {sender_name} กรุณาพิมพ์ค่าความดันในรูปแบบ:\nตัวบน/ตัวล่าง/หัวใจเต้น\n\nตัวอย่าง: 139/77/82"
        line_bot_api.reply_message(reply_token, TextSendMessage(text=msg))
        return
    elif raw_user_text == "พิมพ์ค่าน้ำตาล":
        msg = f"คุณ {sender_name} กรุณาพิมพ์ค่าน้ำตาลในเลือด\n\nตัวอย่าง: 105 หรือ น้ำตาล 105"
        line_bot_api.reply_message(reply_token, TextSendMessage(text=msg))
        return

    is_tagged = ('@' in raw_user_text) or ('ยายชา' in raw_user_text) or ('ห่างภัยNCDs' in raw_user_text)

    if is_tagged:
        clean_question = re.sub(r'@[^\s]+\s*', '', raw_user_text).strip()
        clean_question = re.sub(r'^(ยายชา|ห่างภัยNCDs)\s*', '', clean_question).strip()
        if not clean_question:
            clean_question = raw_user_text

        prompt = (
            f"คุณคือผู้ช่วย AI ด้านสุขภาพประจำครอบครัว ตอบคำถามด้านสุขภาพ คำแนะนำการดูแลตัวเอง โรค NCDs หรือเรื่องอาหาร "
            f"ตอบอย่างกระชับ สุภาพ อ่านง่าย ภาษาไทย และห้ามใช้สัญลักษณ์ดอกจัน (*) ในการจัดข้อความเด็ดขาด "
            f"คำถามจากคุณ {sender_name}: '{clean_question}'"
        )
        
        ai_raw_response = call_gemini_api(prompt)

        if ai_raw_response:
            ai_answer = ai_raw_response.replace('*', '').strip()
            reply_text = f"💡 คำตอบสำหรับคุณ {sender_name}:\n\n{ai_answer}"
        else:
            reply_text = f"ขออภัยครับคุณ {sender_name} ไม่สามารถเชื่อมต่อระบบประมวลผล Gemini ได้ในขณะนี้ (โปรดตรวจสอบ API Key)"

        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
        return

    numbers = re.findall(r'\d+', raw_user_text)
    if len(numbers) >= 2:
        sys_val = int(numbers[0])
        dia_val = int(numbers[1])
        pulse_val = int(numbers[2]) if len(numbers) >= 3 else "-"
        if sys_val > dia_val and 30 <= sys_val <= 300:
            analysis = analyze_bp(sys_val, dia_val)
            reply_text = (
                f"บันทึกผลความดันของคุณ {sender_name} เรียบร้อยครับ\n"
                f"• ตัวบน (SYS): {sys_val} mmHg\n"
                f"• ตัวล่าง (DIA): {dia_val} mmHg\n"
                f"• หัวใจเต้น (PULSE): {pulse_val} bpm\n\n"
                f"{analysis}"
            )
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
            if sys_val >= 140 or dia_val >= 90:
                notify_caregiver("พบค่าความดันสูงผิดปกติ", f"• SYS: {sys_val}, DIA: {dia_val}", sender_name)
            return

    elif len(numbers) == 1 and len(raw_user_text) < 15:
        sugar_val = int(numbers[0])
        if 20 <= sugar_val <= 600:
            analysis = analyze_sugar(sugar_val)
            reply_text = (
                f"บันทึกค่าน้ำตาลของคุณ {sender_name} เรียบร้อยครับ\n"
                f"• ค่าน้ำตาล: {sugar_val} mg/dL\n\n"
                f"{analysis}"
            )
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
            if sugar_val < 70 or sugar_val >= 180:
                notify_caregiver("พบค่าน้ำตาลผิดปกติ", f"• ค่าน้ำตาล: {sugar_val} mg/dL\n{analysis}", sender_name)
            return

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    reply_token = event.reply_token
    sender_name = get_sender_name(event)
    
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = message_content.content
        
        prompt = """Analyze this medical device screen image carefully.
Look for digital numbers on LCD displays, OLED displays, or 7-segment LED displays.
Determine if it is a Blood Pressure Monitor OR a Blood Glucose Monitor.
If Blood Pressure Monitor return JSON: {"type": "bp", "sys": number, "dia": number, "pulse": number}
If Blood Glucose Monitor return JSON: {"type": "sugar", "value": number}
If no numbers return JSON: {"error": true}
Return ONLY raw JSON object. Do not wrap in markdown syntax."""

        resp_text = call_gemini_api(prompt, mime_type="image/jpeg", data_bytes=image_bytes)
        
        if resp_text:
            resp_clean = re.sub(r'```(?:json)?', '', resp_text).replace('```', '').strip()
            match = re.search(r'\{.*\}', resp_clean, re.DOTALL)
            if match:
                data = json.loads(match.group())
                if data.get("type") == "bp" and data.get("sys") and data.get("dia"):
                    sys_val = int(data["sys"])
                    dia_val = int(data["dia"])
                    pulse_val = data.get("pulse", "-")
                    if sys_val > dia_val and 30 <= sys_val <= 300:
                        analysis = analyze_bp(sys_val, dia_val)
                        reply_text = (
                            f"บันทึกผลความดันของคุณ {sender_name} เรียบร้อยครับ\n"
                            f"• ตัวบน (SYS): {sys_val} mmHg\n"
                            f"• ตัวล่าง (DIA): {dia_val} mmHg\n"
                            f"• หัวใจเต้น (PULSE): {pulse_val} bpm\n\n"
                            f"{analysis}"
                        )
                        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
                        if sys_val >= 140 or dia_val >= 90:
                            notify_caregiver("พบค่าความดันสูงผิดปกติ", f"• SYS: {sys_val}, DIA: {dia_val}", sender_name)
                        return

                elif data.get("type") == "sugar" and data.get("value"):
                    sugar_val = int(data["value"])
                    if 20 <= sugar_val <= 600:
                        analysis = analyze_sugar(sugar_val)
                        reply_text = (
                            f"บันทึกค่าน้ำตาลของคุณ {sender_name} เรียบร้อยครับ\n"
                            f"• ค่าน้ำตาล: {sugar_val} mg/dL\n\n"
                            f"{analysis}"
                        )
                        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
                        if sugar_val < 70 or sugar_val >= 180:
                            notify_caregiver("พบค่าน้ำตาลผิดปกติ", f"• ค่าน้ำตาล: {sugar_val} mg/dL", sender_name)
                        return
    except Exception as e:
        print(f"Error processing image: {e}")

    try:
        line_bot_api.reply_message(
            reply_token,
            FlexSendMessage(alt_text="เลือกกรอกข้อมูลความดันหรือน้ำตาล", contents=get_fallback_flex_message())
        )
    except Exception as e:
        print(f"Error sending fallback message: {e}")

@handler.add(MessageEvent, message=AudioMessage)
def handle_audio(event):
    reply_token = event.reply_token
    sender_name = get_sender_name(event)

    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        audio_bytes = message_content.content
        prompt = """Listen to this Thai voice message about medical readings (Blood Pressure or Blood Sugar).
Extract numbers and return ONLY raw JSON format:
For Blood Pressure: {"type": "bp", "sys": number, "dia": number, "pulse": number}
For Blood Sugar: {"type": "sugar", "value": number}
If no numbers: {"error": true}"""

        resp_text = call_gemini_api(prompt, mime_type="audio/m4a", data_bytes=audio_bytes)

        if resp_text:
            match = re.search(r'\{.*\}', resp_text, re.DOTALL)
            if match:
                data = json.loads(match.group())
                if data.get("type") == "bp" and data.get("sys") and data.get("dia"):
                    sys_val = int(data["sys"])
                    dia_val = int(data["dia"])
                    pulse_val = data.get("pulse", "-")
                    analysis = analyze_bp(sys_val, dia_val)
                    reply_text = (
                        f"บันทึกผลความดันจากเสียงพูดของคุณ {sender_name} เรียบร้อยครับ\n"
                        f"• ตัวบน (SYS): {sys_val} mmHg\n"
                        f"• ตัวล่าง (DIA): {dia_val} mmHg\n"
                        f"• หัวใจเต้น (PULSE): {pulse_val} bpm\n\n"
                        f"{analysis}"
                    )
                    line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
                    if sys_val >= 140 or dia_val >= 90:
                        notify_caregiver("พบค่าความดันสูงผิดปกติ (ส่งด้วยเสียง)", f"• SYS: {sys_val}, DIA: {dia_val}", sender_name)
                    return

                elif data.get("type") == "sugar" and data.get("value"):
                    sugar_val = int(data["value"])
                    analysis = analyze_sugar(sugar_val)
                    reply_text = (
                        f"บันทึกค่าน้ำตาลจากเสียงพูดของคุณ {sender_name} เรียบร้อยครับ\n"
                        f"• ค่าน้ำตาล: {sugar_val} mg/dL\n\n"
                        f"{analysis}"
                    )
                    line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
                    if sugar_val < 70 or sugar_val >= 180:
                        notify_caregiver("พบค่าน้ำตาลผิดปกติ (ส่งด้วยเสียง)", f"• ค่าน้ำตาล: {sugar_val} mg/dL", sender_name)
                    return

        line_bot_api.reply_message(reply_token, TextSendMessage(text="⚠️ ไม่สามารถจับใจความตัวเลขจากเสียงได้ กรุณาลองพูดใหม่อีกครั้งครับ"))
    except Exception:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="⚠️ เกิดข้อผิดพลาดในการประมวลผลเสียง"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
