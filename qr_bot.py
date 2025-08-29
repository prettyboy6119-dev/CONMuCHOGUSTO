import logging
import os
from io import BytesIO
from PIL import Image
from pyzbar.pyzbar import decode
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Send me a photo of a QR code and I'll reply with its contents."
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_data = BytesIO()
        await file.download_to_memory(image_data)
        image_data.seek(0)
        img = Image.open(image_data)
        decoded_objs = decode(img)
        if decoded_objs:
            results = '\n'.join([f'`{obj.data.decode("utf-8")}`' for obj in decoded_objs])
            await update.message.reply_text(f"Es con mucho gusto:\n{results}\nQue tengas buen dia!", parse_mode='Markdown')
        else:
            await update.message.reply_text("No QR code found in the image.")
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Failed to process the image.")

def main():
    print("Loaded token:", BOT_TOKEN)
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set in .env")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()

class QRDecoder:
    @staticmethod
    def decode_qr_from_image(image_data):
        try:
            # Convert bytes to PIL Image
            pil_image = Image.open(BytesIO(image_data))
            
            # Convert PIL image to OpenCV format
            cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            
            # Try to decode QR codes
            decoded_objects = pyzbar.decode(cv_image)
            
            if not decoded_objects:
                # Try with grayscale conversion
                gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
                decoded_objects = pyzbar.decode(gray)
            
            if not decoded_objects:
                # Try with different preprocessing
                gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
                # Apply Gaussian blur
                blurred = cv2.GaussianBlur(gray, (5, 5), 0)
                decoded_objects = pyzbar.decode(blurred)
            
            results = []
            for obj in decoded_objects:
                # Decode the data
                qr_data = obj.data.decode('utf-8')
                qr_type = obj.type
                results.append({
                    'data': qr_data,
                    'type': qr_type,
                    'rect': obj.rect
                })
            
            return results
            
        except Exception as e:
            logger.error(f"Error decoding QR code: {e}")
            return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I'm a QR Code decoder bot 🤖\n\n"
        "Send me an image containing a QR code and I'll decode it for you!\n"
        "You can send the image as a photo or document."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🔍 QR Code Decoder Bot Help

How to use:
1. Send me any image containing a QR code
2. I'll analyze the image and extract the QR code data
3. I'll send you back the decoded information

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
    await update.message.reply_text(
        "📸 Please send me an image containing a QR code to decode.\n"
        "You can send it as a photo or document."
    )


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