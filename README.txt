JOB PREP COACH - Setup (Hindi-English)

FILES
- app.py            : Server (login, chapter quiz, mock test, score, chatbox)
- questions.py      : Sawal. Subject -> Chapter -> Sawal ke structure me.
- requirements.txt  : Packages
- Procfile          : Server start command
- templates/        : Screen (HTML)
- static/           : Design (CSS) aur kaam (JavaScript)

NAYA CHAPTER / SAWAL JODNA
questions.py me subject ke andar naya chapter likhein:
    "Naya Chapter Naam": [
        {"q": "Sawal?", "options": ["A", "B", "C", "D"], "answer": 0,
         "solution": "Hal...", "trick": "Shortcut..."},
    ],
answer: sahi option ka number (0=A, 1=B, 2=C, 3=D)

PHONE SE DEPLOY (bina computer)
1. github.com par free account banayein. Repository banayein (naam: job-prep-coach).
2. Is zip ko phone me extract karein, saari files repository me upload karein (folder structure same).
3. render.com par free account banayein. "New Web Service" -> GitHub repo connect karein.
4. Build command: pip install -r requirements.txt
   Start command: gunicorn app:app
5. Environment (Environment Variables) me ye daalein:
   GEMINI_API_KEY = Google AI Studio (aistudio.google.com) se banayi hui free key
   SECRET_KEY    = koi bhi lamba random text
6. Deploy karein. Jo link mile, wahi app ka link hai.

ZAROORI BAATEIN
- Login ab real hai: number + password. Password server me safe (hash) rehta hai.
- Chat free Gemini key se chalta hai. Free limit din me kam hoti hai. Agar 429 error aaye to thodi der baad try karein.
- Free Render par data restart hone par delete ho sakta hai (users aur scores). Asli use ke liye paid database lena padega.
- Asli OTP SMS ke liye baad me SMS provider jodenge.
