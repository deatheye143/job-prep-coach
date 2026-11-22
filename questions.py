# STRUCTURE: subject -> chapter -> sawal list
# Har sawal: q (sawal), options (4 option), answer (sahi option: 0=A,1=B,2=C,3=D),
#            solution (hal), trick (shortcut)
# Naya chapter jodne ke liye: "Chapter Naam": [ {...}, {...} ],

SUBJECTS = {"math": "Math", "reasoning": "Reasoning", "gs": "General Studies",
            "english": "English", "computer": "Computer", "odia": "Odia"}

QUESTIONS = {
    "math": {
        "Percentage": [
            {"q": "15% of 240 kitna hota hai?", "options": ["30", "36", "40", "48"], "answer": 1,
             "solution": "240 x 15 / 100 = 36.",
             "trick": "10% = 24, 5% = 12 (aadha). Total = 24 + 12 = 36."},
        ],
        "Speed, Distance & Time": [
            {"q": "Ek train 60 km/h ki speed se 3 ghante chalti hai. Kitni doori tay karegi?", "options": ["120 km", "160 km", "180 km", "200 km"], "answer": 2,
             "solution": "Doori = Speed x Time = 60 x 3 = 180 km.",
             "trick": "Speed x Time seedha karo. 60 ko 3 se guna karo: 180."},
        ],
        "Unitary Method": [
            {"q": "5 pen ki keemat ₹40 hai. 12 pen ki keemat kitni hogi?", "options": ["₹88", "₹92", "₹96", "₹100"], "answer": 2,
             "solution": "1 pen = ₹40 / 5 = ₹8. 12 pen = 12 x 8 = ₹96.",
             "trick": "Pehle 1 ki keemat nikaalo, phir guna karo. Ya seedha: 40 x 12 / 5 = 96."},
        ],
        "Number Series": [
            {"q": "Series 2, 6, 12, 20, ? (agla number)", "options": ["24", "28", "30", "32"], "answer": 2,
             "solution": "Difference: 4, 6, 8, agla difference 10. 20 + 10 = 30.",
             "trick": "Difference dekho: 4, 6, 8 me +2 ho raha hai. Agla difference 10 hoga."},
        ],
    },
    "reasoning": {
        "Analogy": [
            {"q": "Cat : Kitten :: Dog : ?", "options": ["Puppy", "Bark", "Tail", "Bone"], "answer": 0,
             "solution": "Cat ka baccha Kitten hai, waise hi Dog ka baccha Puppy hai.",
             "trick": "Relation pehle pakdo: bada jaanwar -> uska baccha."},
        ],
        "Letter Series": [
            {"q": "Series A, C, F, J, ? (agla letter)", "options": ["M", "N", "O", "P"], "answer": 2,
             "solution": "A=1, C=3, F=6, J=10, agla = 15 = O. Gap: +2, +3, +4, +5.",
             "trick": "Letters ke beech ka gap badhta jaata hai: +2, +3, +4, phir +5. J (10) + 5 = O (15)."},
        ],
        "Direction": [
            {"q": "Ladki uttar disha me dekh rahi hai aur right taraf 90° mudti hai. Ab wo kis disha me dekh rahi hai?", "options": ["Purab (East)", "Pashchim (West)", "Dakshin (South)", "Uttar (North)"], "answer": 0,
             "solution": "Right mudne par North se East ki taraf ghoomte hain.",
             "trick": "Clockwise order yaad rakho: N -> E -> S -> W. Right = clockwise, Left = ulta."},
        ],
        "Odd One Out": [
            {"q": "Alag kaun hai?", "options": ["Seb", "Kela", "Gajar", "Angoor"], "answer": 2,
             "solution": "Seb, Kela, Angoor fruit hain. Gajar sabzi hai.",
             "trick": "Group ka common category dhundho (fruit). Jo us category me na ho, wahi alag hai."},
        ],
    },
    "gs": {
        "Capital (Rajdhani)": [
            {"q": "Bharat ki rajdhani kaun si hai?", "options": ["Mumbai", "Kolkata", "New Delhi", "Chennai"], "answer": 2,
             "solution": "Bharat ki rajdhani New Delhi hai, jahan Sansad Bhawan hai.",
             "trick": "Mumbai financial capital hai, Kolkata aur Chennai state capital. Rajdhani = Delhi."},
        ],
        "National Symbols": [
            {"q": "Bharat ka rashtriya pakshi kaun sa hai?", "options": ["Mor (Peacock)", "Koyal", "Tota", "Hans"], "answer": 0,
             "solution": "Mor (Peacock) Bharat ka rashtriya pakshi hai.",
             "trick": "Rashtriya pratik yaad rakho: Pakshi = Mor, Pashu = Bagh, Phool = Kamal."},
        ],
        "Odisha": [
            {"q": "Odisha ki rajdhani kaun si hai?", "options": ["Cuttack", "Bhubaneswar", "Puri", "Rourkela"], "answer": 1,
             "solution": "Odisha ki rajdhani Bhubaneswar hai.",
             "trick": "Puri (Jagannath Dham) aur Cuttack bhi Odisha ke bade shehar hain, par rajdhani Bhubaneswar hai."},
        ],
        "Constitution": [
            {"q": "Bharat ka Samvidhan kis tareekh ko lagu hua?", "options": ["15 Aug 1947", "26 Jan 1950", "2 Oct 1947", "26 Nov 1949"], "answer": 1,
             "solution": "Samvidhan 26 Nov 1949 ko bana aur 26 Jan 1950 ko lagu hua.",
             "trick": "15 Aug 1947 = Azadi. 26 Jan 1950 = Gantantra Diwas (Republic Day)."},
        ],
    },
    "english": {
        "Spelling": [
            {"q": "Sahi spelling kaun si hai?", "options": ["Recieve", "Receive", "Receve", "Recive"], "answer": 1,
             "solution": "Sahi spelling: Receive.",
             "trick": "Rule: 'i before e, except after c' -> re-CEI-ve."},
        ],
        "Synonyms": [
            {"q": "'Happy' ka synonym kya hai?", "options": ["Sad", "Joyful", "Angry", "Tired"], "answer": 1,
             "solution": "Synonym ka matlab same meaning. Happy = Joyful.",
             "trick": "Sad aur Angry ulte meaning ke hain. Jo option khushi bataye, wahi synonym hai."},
        ],
        "Antonyms": [
            {"q": "'Brave' ka antonym kya hai?", "options": ["Bold", "Courageous", "Cowardly", "Strong"], "answer": 2,
             "solution": "Antonym ka matlab ulta meaning. Brave ka ulta Cowardly (darpok).",
             "trick": "Bold, Courageous, Strong sab Brave ke jaise hain. Jo ulta ho, wahi antonym."},
        ],
        "Grammar (Tense)": [
            {"q": "She ___ to school every day.", "options": ["go", "goes", "going", "gone"], "answer": 1,
             "solution": "She (ek vyakti) ke saath present simple me verb me 's' lagta hai: goes.",
             "trick": "He / She / It ke saath verb me 's' ya 'es' lagta hai."},
        ],
    },
    "computer": {
        "Computer Basics": [
            {"q": "RAM ka full form kya hai?", "options": ["Random Access Memory", "Read Access Memory", "Run Available Memory", "Random Application Memory"], "answer": 0,
             "solution": "RAM = Random Access Memory.",
             "trick": "RAM temporary memory hai: band hone par data chala jata hai."},
            {"q": "Computer ka brain kise kehte hain?", "options": ["RAM", "Hard Disk", "CPU", "Monitor"], "answer": 2,
             "solution": "CPU (Central Processing Unit) sab calculations karta hai, isliye ise brain kehte hain.",
             "trick": "CPU = Central Processing Unit = Brain. Storage ya display brain nahi hote."},
        ],
        "Input & Output": [
            {"q": "Output device kaun sa hai?", "options": ["Keyboard", "Mouse", "Printer", "Scanner"], "answer": 2,
             "solution": "Printer se result kagaz par aata hai, isliye ye output device hai.",
             "trick": "Input = Keyboard, Mouse, Scanner (data andar). Output = Printer, Monitor, Speaker (data bahar)."},
        ],
        "Memory Units": [
            {"q": "1 KB me kitne bytes hote hain?", "options": ["1000", "1024", "100", "512"], "answer": 1,
             "solution": "1 KB = 1024 bytes.",
             "trick": "Computer me 2 ki power use hoti hai: 2^10 = 1024."},
        ],
    },
    "odia": {
        "Language & Script": [
            {"q": "Odia bhasha kis lipi me likhi jaati hai?", "options": ["Devanagari", "Odia lipi", "Bengali", "Gurmukhi"], "answer": 1,
             "solution": "Odia bhasha ki apni lipi (Odia script) hai.",
             "trick": "Odia lipi Bengali se milti lagti hai, par alag hai. Devanagari Hindi/Marathi ki lipi hai."},
        ],
        "Culture & Festivals": [
            {"q": "Puri ke Rath Yatra me kis bhagwan ki yatra hoti hai?", "options": ["Shiva", "Jagannath", "Ram", "Krishna"], "answer": 1,
             "solution": "Puri ki Rath Yatra Bhagwan Jagannath ki hoti hai.",
             "trick": "Puri = Jagannath Dham. Jo shehar ka naam, wahi bhagwan yaad rakho."},
        ],
        "Geography": [
            {"q": "Odisha ki pramukh nadi kaun si hai?", "options": ["Mahanadi", "Ganga", "Godavari", "Narmada"], "answer": 0,
             "solution": "Mahanadi Odisha ki sabse badi aur pramukh nadi hai.",
             "trick": "Odisha ki nadi ka naam 'Maha' se shuru hota hai: Mahanadi. Ganga, Narmada dusre rajya me hain."},
        ],
        "Literature": [
            {"q": "'Kabi Samrat' ki upadhi kisko mili thi?", "options": ["Fakir Mohan Senapati", "Upendra Bhanja", "Gopabandhu Das", "Madhusudan Rao"], "answer": 1,
             "solution": "Odia sahitya me Upendra Bhanja ko 'Kabi Samrat' kaha jata hai.",
             "trick": "Kabi Samrat = Upendra Bhanja. Fakir Mohan ko 'Sahitya Samrat' kaha jata hai."},
        ],
    },
}
