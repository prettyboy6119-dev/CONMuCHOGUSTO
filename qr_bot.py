import logging
import os
from io import BytesIO
from PIL import Image
from pyzbar.pyzbar import decode
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv
import ast
import re

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

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

def looks_like_math(text: str) -> bool:
    """Heuristic: text contains only math tokens and at least one operator."""
    if not text:
        return False
    if not _MATH_TOKEN_RE.match(text):
        return False
    return any(op in text for op in ['+', '-', '*', '×', 'x', 'X', '/', '÷', '%', '^'])

class QRDecoder:
    @staticmethod
    def decode_qr_from_image(image_data):
        try:
            # Open image from bytes
            pil_image = Image.open(BytesIO(image_data))
            decoded_objects = decode(pil_image)

            results = []
            for obj in decoded_objects:
                qr_data = obj.data.decode('utf-8')
                qr_type = getattr(obj, 'type', 'QR_CODE')
                results.append({
                    'data': qr_data,
                    'type': qr_type,
                    'rect': getattr(obj, 'rect', None)
                })

            return results

        except Exception as e:
            logger.error(f"Error decoding QR code: {e}")
            return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I'm a QR Code decoder bot 🤖\n\n"
        "• Send me an image containing a QR code and I'll decode it for you.\n"
        "• Or send me a math expression (e.g., 12*(3+4)/2) and I'll calculate it.\n\n"
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
• Supported operators: +, -, *, /, %, **, //, parentheses, and unary +/-. Caret (^) is treated as power.

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
    """
    await update.message.reply_text(help_text)


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
    await update.message.reply_text("🔍 Analyzing image for QR codes...")
    
    # Decode QR codes
    qr_decoder = QRDecoder()
    results = qr_decoder.decode_qr_from_image(image_data)
    
    if results:
        if len(results) == 1:
            result = results[0]
            response = f"✅ QR Code decoded successfully!\n\n"
            response += f"**Type:** {result['type']}\n"
            response += f"**Content:**\n`{result['data']}`"
            
            await update.message.reply_text(response, parse_mode='Markdown')
        else:
            response = f"✅ Found {len(results)} QR codes:\n\n"
            for i, result in enumerate(results, 1):
                response += f"**QR Code #{i}**\n"
                response += f"Type: {result['type']}\n"
                response += f"Content: `{result['data']}`\n\n"
            
            await update.message.reply_text(response, parse_mode='Markdown')
    else:
        await update.message.reply_text(
            "❌ No QR codes found in the image.\n\n"
            "Tips:\n"
            "• Make sure the QR code is clearly visible\n"
            "• Check that the image has good lighting\n"
            "• Try sending a higher quality image"
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = (update.message.text or '').strip()
        if looks_like_math(text):
            # Normalize caret to power for user convenience
            normalized = text.replace('^', '**').replace('x', '*').replace('X', '*')
            result = _safe_eval_expr(normalized)
            # Render as integer if whole number, otherwise round to 5 decimal places
            if isinstance(result, float):
                if result.is_integer():
                    result = int(result)
                else:
                    result = round(result, 5)
            await update.message.reply_text(f"```\n{text} = {result}\n```", parse_mode='Markdown')
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
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🤖 QR Code Decoder Bot is starting...")
    print("✅ Bot is running! Press Ctrl+C to stop.")
    
    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()