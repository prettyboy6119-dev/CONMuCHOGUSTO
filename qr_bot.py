import logging
import math
import os
import random
from html import escape
from io import BytesIO
from PIL import Image
import cv2
import numpy as np
from pyzbar.pyzbar import ZBarSymbol, decode
from telegram import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv
import ast
import re

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BOT_PUBLIC_URL = os.getenv("BOT_PUBLIC_URL", "https://t.me/conmuchogusto_bot")
ENABLE_QREADER = os.getenv("ENABLE_QREADER", "").lower() in {"1", "true", "yes", "on"}
_QREADER = None

QR_CAPTION_PHRASES = (
    "Con placer",
    "Con mucho gusto",
    "Con todo el gusto",
    "Con muchísimo gusto",
    "Será un placer",
    "Encantado de ayudar",
    "A la orden",
)
TELEGRAM_CAPTION_LIMIT = 1024

def _safe_eval_expr(expr: str) -> float:
    """Safely evaluate a basic arithmetic expression using AST.

    Allowed: +, -, *, /, %, **, //, parentheses, unary +/-, integers and floats.
    """
    # Normalize some unicode operators
    expr = expr.replace('×', '*').replace('÷', '/').replace('–', '-').replace('−', '-')

    # Parse to AST
    node = ast.parse(expr, mode='eval')

    allowed_binops = (
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.FloorDiv
    )

    def _eval(n):
        if isinstance(n, ast.Expression):
            return _eval(n.body)
        if isinstance(n, ast.Num):  # Py<3.8
            return n.n
        if hasattr(ast, 'Constant') and isinstance(n, ast.Constant):  # Py>=3.8
            if isinstance(n.value, (int, float)):
                return n.value
            raise ValueError("Only numeric constants are allowed")
        if isinstance(n, ast.BinOp) and isinstance(n.op, allowed_binops):
            left = _eval(n.left)
            right = _eval(n.right)
            if isinstance(n.op, ast.Add):
                return left + right
            if isinstance(n.op, ast.Sub):
                return left - right
            if isinstance(n.op, ast.Mult):
                return left * right
            if isinstance(n.op, ast.Div):
                return left / right
            if isinstance(n.op, ast.Mod):
                return left % right
            if isinstance(n.op, ast.Pow):
                return left ** right
            if isinstance(n.op, ast.FloorDiv):
                return left // right
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            operand = _eval(n.operand)
            if isinstance(n.op, ast.UAdd):
                return +operand
            return -operand
        if isinstance(n, ast.Tuple):  # Prevent tuple expressions
            raise ValueError("Tuples are not allowed")
        # Disallow everything else (names, calls, attributes, etc.)
        raise ValueError("Invalid or unsafe expression")

    return _eval(node)

_MATH_TOKEN_RE = re.compile(r"^[\s\d\.+\-*/%()xX×÷,^]+$")
_BOT_MENTION_RE = re.compile(r"@([A-Za-z0-9_]{5,32})\b")

def looks_like_math(text: str) -> bool:
    """Heuristic: text contains only math tokens and at least one operator."""
    if not text:
        return False
    if not _MATH_TOKEN_RE.match(text):
        return False
    return any(op in text for op in ['+', '-', '*', '×', 'x', 'X', '/', '÷', '%', '^'])


def extract_math_expression(text: str):
    """Return the longest math-looking span from casual text."""
    if not text:
        return None

    allowed_chars = set("0123456789. +-*/%()xX×÷,^–−\t\n\r")
    candidates = []
    current = []

    for char in text:
        if char in allowed_chars:
            current.append(char)
        elif current:
            candidates.append("".join(current).strip(" \t\r\n,"))
            current = []

    if current:
        candidates.append("".join(current).strip(" \t\r\n,"))

    candidates = [candidate for candidate in candidates if looks_like_math(candidate)]
    if not candidates:
        return None

    return max(candidates, key=len).strip()


def expression_from_mention(text: str, bot_username: str):
    if not text or not bot_username:
        return None

    mention = f"@{bot_username.lower()}"
    parts = []
    mentioned = False
    cursor = 0

    for match in _BOT_MENTION_RE.finditer(text):
        if match.group(0).lower() == mention:
            parts.append(text[cursor:match.start()])
            cursor = match.end()
            mentioned = True

    if not mentioned:
        return None

    parts.append(text[cursor:])
    mentionless_text = " ".join(part.strip() for part in parts if part.strip())
    return extract_math_expression(mentionless_text)


def command_args_from_text(text: str, command: str, bot_username: str = ""):
    if not text:
        return None

    pattern = rf"^/{re.escape(command)}(?:@([A-Za-z0-9_]{{5,32}}))?(?:\s+(.*))?$"
    match = re.match(pattern, text.strip(), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None

    target_username = match.group(1)
    if target_username and bot_username and target_username.lower() != bot_username.lower():
        return None

    return (match.group(2) or "").strip()


async def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    username = getattr(context.bot, "username", None)
    if username:
        return username

    bot_info = await context.bot.get_me()
    return bot_info.username or ""


def format_calculation_result(expression: str, result):
    if isinstance(result, float):
        if result.is_integer():
            result = int(result)
        else:
            result = round(result, 5)
    return f"{expression} = {result}"


async def reply_calculation(update: Update, expression: str):
    normalized = expression.replace('^', '**').replace('x', '*').replace('X', '*')
    result = _safe_eval_expr(normalized)
    response = escape(format_calculation_result(expression, result))
    await update.message.reply_text(f"<code>{response}</code>", parse_mode="HTML")


def qr_png_from_text(text: str):
    encoder = cv2.QRCodeEncoder_create()
    image = encoder.encode(text)

    # OpenCV returns a module-sized bitmap. Sending that tiny image through
    # Telegram makes clients enlarge it with interpolation, which looks blurry.
    # Add a standard quiet zone and enlarge by a whole-number scale factor so
    # every QR module remains a perfectly square block of pixels.
    image = np.where(image > 127, 255, 0).astype(np.uint8)
    image = cv2.copyMakeBorder(
        image,
        4,
        4,
        4,
        4,
        borderType=cv2.BORDER_CONSTANT,
        value=255,
    )
    module_scale = max(1, math.ceil(1024 / max(image.shape)))
    image = cv2.resize(
        image,
        (image.shape[1] * module_scale, image.shape[0] * module_scale),
        interpolation=cv2.INTER_NEAREST,
    )

    ok, buffer = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    if not ok:
        raise ValueError("Could not encode QR image")

    output = BytesIO(buffer.tobytes())
    output.name = "qr.png"
    output.seek(0)
    return output


def linked_bot_phrase(phrase: str = None):
    """Return a randomized friendly phrase linked to this Telegram bot."""
    phrase = phrase or random.choice(QR_CAPTION_PHRASES)
    return phrase, (
        f'<a href="{escape(BOT_PUBLIC_URL, quote=True)}">'
        f"{escape(phrase)} ✨</a>"
    )


def qr_caption(text: str, phrase: str = None):
    """Build a copyable HTML caption ending in a friendly bot link."""
    phrase, linked_phrase = linked_bot_phrase(phrase)
    visible_footer = f"\n\n{phrase} ✨"
    if len(text) + len(visible_footer) <= TELEGRAM_CAPTION_LIMIT:
        return f"<code>{escape(text)}</code>\n\n{linked_phrase}", None, None

    suffix = "\n\n…"
    available = TELEGRAM_CAPTION_LIMIT - len(suffix)
    return f"<code>{escape(text[:available])}</code>{suffix}", text, linked_phrase


async def reply_qr(update: Update, text: str):
    text = text.strip()
    if not text:
        await update.message.reply_text("Usage: /qr text to encode")
        return
    if len(text.encode("utf-8")) > 2000:
        await update.message.reply_text("❌ That text is too long for a practical QR code. Please keep it under 2000 bytes.")
        return

    qr_image = qr_png_from_text(text)
    caption, overflow_content, overflow_footer = qr_caption(text)
    # The source is a large, integer-scaled PNG, so it remains readable after
    # Telegram renders it as an inline photo instead of a downloadable file.
    await update.message.reply_photo(
        photo=qr_image,
        caption=caption,
        parse_mode="HTML",
    )
    if overflow_content:
        await update.message.reply_text(
            f"<code>{escape(overflow_content)}</code>\n\n{overflow_footer}",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


def decoded_qr_reply_markup(content: str):
    """Return Telegram's native one-tap copy button when content fits."""
    if not content or len(content) > 256:
        return None

    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(
                "📋 Copy content",
                copy_text=CopyTextButton(content),
            )
        ]]
    )


async def reply_decoded_result(message, result):
    content = result["data"]
    _, linked_phrase = linked_bot_phrase()
    response = f"<code>{escape(content)}</code>\n\n{linked_phrase}"
    reply_markup = decoded_qr_reply_markup(content)

    await message.reply_text(
        response,
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )

class QRDecoder:
    def __init__(self):
        self.detector = cv2.QRCodeDetector()
        if hasattr(self.detector, "setUseAlignmentMarkers"):
            self.detector.setUseAlignmentMarkers(True)

    @staticmethod
    def _result(data, source, qr_type="QRCODE", rect=None):
        return {
            "data": data,
            "type": qr_type,
            "rect": rect,
            "source": source,
        }

    @staticmethod
    def _safe_decode_bytes(value):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("utf-8", errors="replace")

    @staticmethod
    def _normalize_points(points):
        if points is None:
            return None
        try:
            return np.asarray(points).round(2).tolist()
        except Exception:
            return None

    @staticmethod
    def _add_unique(results, seen, result):
        key = (result["type"], result["data"])
        if result["data"] and key not in seen:
            seen.add(key)
            results.append(result)

    @staticmethod
    def _image_variants(rgb_image):
        yield "original", rgb_image

        height, width = rgb_image.shape[:2]
        max_side = max(height, width)
        if max_side < 1800:
            scale = min(3.0, 1800 / max_side)
            enlarged = cv2.resize(
                rgb_image,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_CUBIC,
            )
            yield "upscaled", enlarged

        gray = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        yield "contrast", cv2.cvtColor(clahe, cv2.COLOR_GRAY2RGB)

        sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        sharpened = cv2.filter2D(rgb_image, -1, sharpen_kernel)
        yield "sharpened", sharpened

        adaptive = cv2.adaptiveThreshold(
            clahe,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            2,
        )
        yield "threshold", cv2.cvtColor(adaptive, cv2.COLOR_GRAY2RGB)

    def _decode_with_opencv(self, variant_name, rgb_image, results, seen):
        bgr_image = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR)

        try:
            ok, decoded_info, points, _ = self.detector.detectAndDecodeMulti(bgr_image)
            if ok:
                point_list = points if points is not None else [None] * len(decoded_info)
                for data, point in zip(decoded_info, point_list):
                    self._add_unique(
                        results,
                        seen,
                        self._result(
                            data,
                            f"opencv-multi:{variant_name}",
                            rect=self._normalize_points(point),
                        ),
                    )
        except cv2.error as exc:
            logger.debug("OpenCV multi QR decode failed on %s: %s", variant_name, exc)

        for method_name, method in (
            ("opencv", self.detector.detectAndDecode),
            ("opencv-curved", self.detector.detectAndDecodeCurved),
        ):
            try:
                data, points, _ = method(bgr_image)
                self._add_unique(
                    results,
                    seen,
                    self._result(
                        data,
                        f"{method_name}:{variant_name}",
                        rect=self._normalize_points(points),
                    ),
                )
            except cv2.error as exc:
                logger.debug("%s QR decode failed on %s: %s", method_name, variant_name, exc)

    def _decode_with_pyzbar(self, variant_name, rgb_image, results, seen):
        gray = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2GRAY)
        height, width = gray.shape[:2]
        decoded_objects = decode(
            (gray.tobytes(), width, height),
            symbols=[ZBarSymbol.QRCODE],
        )

        for obj in decoded_objects:
            qr_data = self._safe_decode_bytes(obj.data)
            self._add_unique(
                results,
                seen,
                self._result(
                    qr_data,
                    f"pyzbar:{variant_name}",
                    qr_type=getattr(obj, "type", "QRCODE"),
                    rect=getattr(obj, "rect", None),
                ),
            )

    def _decode_with_qreader(self, rgb_image, results, seen):
        if not ENABLE_QREADER:
            return

        global _QREADER
        try:
            if _QREADER is None:
                from qreader import QReader

                _QREADER = QReader()
            decoded_items = _QREADER.detect_and_decode(image=rgb_image)
        except ImportError:
            logger.warning("ENABLE_QREADER is set, but qreader is not installed.")
            return
        except Exception as exc:
            logger.warning("QReader decode failed: %s", exc)
            return

        for data in decoded_items:
            if data:
                self._add_unique(results, seen, self._result(data, "qreader"))

    def decode_qr_from_image(self, image_data):
        try:
            results = []
            seen = set()

            pil_image = Image.open(BytesIO(image_data)).convert("RGB")
            rgb_image = np.array(pil_image)

            self._decode_with_qreader(rgb_image, results, seen)

            for variant_name, variant in self._image_variants(rgb_image):
                self._decode_with_opencv(variant_name, variant, results, seen)
                self._decode_with_pyzbar(variant_name, variant, results, seen)

            return results

        except Exception as e:
            logger.error(f"Error decoding QR code: {e}")
            return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I'm a QR Code decoder bot 🤖\n\n"
        "• Send me an image containing a QR code and I'll decode it for you.\n"
        "• Or send me a math expression (e.g., 12*(3+4)/2) and I'll calculate it.\n\n"
        "In group chats, mention me with a calculation, like @BotUsername 12*(3+4).\n"
        "Use /qr followed by text and I'll generate a QR code.\n"
        "You can send images as a photo or document."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🔍 QR Code Decoder Bot Help

How to use:
1. Send me any image containing a QR code
2. I'll analyze the image and extract the QR code data
3. I'll send you back the decoded information

Calculator:
• Send a math expression like `12*(3+4)/2`, `5^3 - 7`, or `10 ÷ 4` and I'll reply with the result.
• In group chats, mention me with the expression, for example: `@BotUsername 12*(3+4)/2`.
• If group privacy mode is enabled, use `/calc@BotUsername 12*(3+4)/2`.
• Supported operators: +, -, *, /, %, **, //, parentheses, and unary +/-. Caret (^) is treated as power.

QR generator:
• Use `/qr some text or link` and I'll send back a QR code image.
• In group chats, use `/qr@BotUsername some text or link`.

Supported formats:
• Photos sent directly through Telegram
• Images sent as documents
• Most common image formats (JPEG, PNG, etc.)

Tips for better results:
• Ensure the QR code is clearly visible
• Good lighting helps with detection
• The QR code should be reasonably sized in the image

Commands:
/start - Start the bot
/help - Show this help message
/calc - Calculate an expression
/qr - Generate a QR code from text
    """
    await update.message.reply_text(help_text)


async def calc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        expression = extract_math_expression(" ".join(context.args))
        if expression and looks_like_math(expression):
            await reply_calculation(update, expression)
        else:
            await update.message.reply_text("Usage: /calc 12*(3+4)/2")
    except Exception as e:
        logger.error(f"Error evaluating /calc expression: {e}")
        await update.message.reply_text("❌ Sorry, I couldn't evaluate that expression. Make sure it's basic arithmetic only.")


async def qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await reply_qr(update, " ".join(context.args))
    except Exception as e:
        logger.error(f"Error generating QR code: {e}")
        await update.message.reply_text("❌ Sorry, I couldn't generate that QR code.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Get the largest photo size
        photo = update.message.photo[-1]
        
        # Download the photo
        file = await context.bot.get_file(photo.file_id)
        
        # Get image data
        image_data = BytesIO()
        await file.download_to_memory(image_data)
        image_data.seek(0)
        
        # Process the image
        await process_image(update, image_data.getvalue())
        
    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await update.message.reply_text("❌ Sorry, I couldn't process your photo. Please try again.")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        document = update.message.document
        
        # Check if it's an image
        if document.mime_type and document.mime_type.startswith('image/'):
            # Download the document
            file = await context.bot.get_file(document.file_id)
            
            # Get image data
            image_data = BytesIO()
            await file.download_to_memory(image_data)
            image_data.seek(0)
            
            # Process the image
            await process_image(update, image_data.getvalue())
        else:
            await update.message.reply_text("📄 Please send an image file containing a QR code.")
            
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        await update.message.reply_text("❌ Sorry, I couldn't process your document. Please try again.")


async def process_image(update: Update, image_data):
    status_message = await update.message.reply_text("🔍 Analyzing image for QR codes...")

    try:
        # Decode QR codes
        qr_decoder = QRDecoder()
        results = qr_decoder.decode_qr_from_image(image_data)

        if results:
            if len(results) == 1:
                await reply_decoded_result(update.message, results[0])
            else:
                for result in results:
                    await reply_decoded_result(update.message, result)
        else:
            await update.message.reply_text(
                "❌ No QR codes found in the image.\n\n"
                "Tips:\n"
                "• Make sure the QR code is clearly visible\n"
                "• Check that the image has good lighting\n"
                "• Try sending a higher quality image"
            )
    finally:
        try:
            await status_message.delete()
        except Exception as exc:
            logger.debug("Could not delete QR analysis status message: %s", exc)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = (update.message.text or '').strip()
        chat_type = getattr(update.effective_chat, "type", "private")
        bot_username = await get_bot_username(context)

        calc_args = command_args_from_text(text, "calc", bot_username)
        if calc_args is not None:
            expression = extract_math_expression(calc_args)
            if expression and looks_like_math(expression):
                await reply_calculation(update, expression)
            else:
                await update.message.reply_text("Usage: /calc 12*(3+4)/2")
            return

        qr_args = command_args_from_text(text, "qr", bot_username)
        if qr_args is not None:
            await reply_qr(update, qr_args)
            return

        if chat_type in {"group", "supergroup"}:
            expression = expression_from_mention(text, bot_username)
            if expression and looks_like_math(expression):
                await reply_calculation(update, expression)
            return

        expression = extract_math_expression(text)
        if expression and expression == text and looks_like_math(expression):
            await reply_calculation(update, expression)
        else:
            await update.message.reply_text(
                "📸 Please send me an image containing a QR code to decode.\n"
                "You can send it as a photo or document."
            )
    except Exception as e:
        logger.error(f"Error evaluating expression: {e}")
        await update.message.reply_text("❌ Sorry, I couldn't evaluate that expression. Make sure it's basic arithmetic only.")


def main():
    # Get bot token from environment variable
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        print("❌ Error: TELEGRAM_BOT_TOKEN environment variable not set!")
        print("Please set your bot token: export TELEGRAM_BOT_TOKEN='your_token_here'")
        return
    
    # Create application
    application = Application.builder().token(token).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("calc", calc_command))
    application.add_handler(CommandHandler("qr", qr_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT, handle_text))
    
    print("🤖 QR Code Decoder Bot is starting...")
    print("✅ Bot is running! Press Ctrl+C to stop.")
    
    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
