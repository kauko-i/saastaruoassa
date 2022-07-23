from flask import Flask, Response, render_template, request
from flask_caching import Cache
import urllib.request
import re
from scipy.optimize import linprog
import os
import psycopg2
import urllib.request
from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, IntegerField
from wtforms.validators import DataRequired, NumberRange, Optional
from flask_wtf.csrf import CSRFProtect

config = {
    "DEBUG": False,
    "CACHE_TYPE": "SimpleCache",
}

app = Flask(__name__)
app.config.from_mapping(config)
app.secret_key = os.environ['SECRET_KEY']
CSRFProtect(app)
cache = Cache(app)

JOULEA_KALORISSA = 4.18
RASVAN_ENERGIA = 0.037
PROTEIININ_ENERGIA = 0.017
DATABASE_URL = os.environ['DATABASE_URL']
ENERGIA_YLARAJA = 1.001
MILLIGRAMMAA_PER_GRAMMA = 1000
I_INDEKSI = 27
B12_INDEKSI = 17
DHA_INDEKSI = 9

def t(A):
	palaute = []
	for i in range(len(A[0])):
		palaute.append([])
		for j in range(len(A)):
			palaute[i].append(0)
	for i in range(len(A)):
		for j in range(len(A[i])):
			palaute[j][i] = A[i][j]
	return palaute

def ryhmat2iat(ryhmat):
    tuplatpois = sorted(list(map(lambda x: x[1:], filter(lambda x: 'N' not in x, ryhmat))),key=int)
    palaute = map(lambda i: '{}-{}'.format(tuplatpois[i], int(tuplatpois[i + 1]) - 1) if i < len(tuplatpois) - 1 else '>{}'.format(tuplatpois[i]), range(len(tuplatpois)))
    return sorted(palaute, key=lambda x: int(x.split('-')[0].replace('>', '')))

ALKU = "https://www.s-kaupat.fi/tuote/"
HINTAPAATTEET = ["€/kg", "€/l"]

@cache.cached(timeout=86400)
def hinnat(osoitteet):
    palaute = []
    for rivi in osoitteet:
        osoite = ALKU + rivi
        fp = urllib.request.urlopen(osoite)
        html = fp.read().decode("utf8")
        hinta = None
        for i in range(len(HINTAPAATTEET)):
            hinta = re.search("\d*,\d* {}".format(HINTAPAATTEET[i]), html)
            if hinta:
                hinta = hinta.group(0)[:-len(HINTAPAATTEET[i])]
                break
        fp.close()
        palaute.append(None if hinta is None else float(hinta.replace(",", "."))/10)
    return palaute

def syote2tulos(ika, sukupuoli, energia, keliakia, laktoosi, kasvis, vege, proteiini):
    # Lomake käyttää kilokaloreita, tietokannat jouleja
    energia = int(energia)*JOULEA_KALORISSA

    # Tietokanta yksilöi ikäryhmät alarajan perusteella
    ika = ''.join(filter(str.isdigit, ika.split('-')[0]))

    # Muodosta b-vektorit ja A-matriisit
    b = [ENERGIA_YLARAJA*energia,-energia]
    A = []
    nimet = []
    osoitteet = []
    ryhma = sukupuoli[0] + ika
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    gluteenia = []
    laktoosia = []
    lihaa = []
    elainperainen = []
    with conn:
        with conn.cursor() as curs:
            # Hae rasvojen prosentteina annetut suositukset ja laske milligrammamäärät.
            curs.execute('SELECT rasvat,kertarasvat,monirasvat,n3,alfalinoleeni,linoli FROM saannit WHERE ryhma = %s;', (ryhma,))
            for rivi in curs:
                for i in range(len(rivi)):
                    b.append(-float(str(rivi[i])[:-1])/100*energia/RASVAN_ENERGIA)
            # Hae proteiinien prosentteina annettu suositus ja laske milligrammamäärä.
            if not proteiini:
                curs.execute('SELECT proteiini FROM saannit WHERE ryhma = %s;', (ryhma,))
                for rivi in curs:
                    b.append(-float(str(rivi[0])[:-1])/100*energia/PROTEIININ_ENERGIA)
            else:
                b.append(-int(proteiini)*MILLIGRAMMAA_PER_GRAMMA)
            # Hae milligrammoina annetut suositukset
            curs.execute('SELECT dha,kuitu,a,b1,b2,b3,b6,b9,b12,c,d,e,ca,p,k,mg,fe,zn,i,se FROM saannit WHERE ryhma = %s', (ryhma,))
            for rivi in curs:
                for i in range(len(rivi)):
                    b.append(-float(rivi[i]))

            curs.execute('''SELECT energia,rasva,kertarasva,monirasva,n3,alfa,linoli,proteiini,
                        dha,kuitu,a,b1,b2,b3,b6,b9,b12,c,d,e,ca,p,k,mg,fe,zn,i,se FROM arvot;''')
            for rivi in curs:
                A.append([float(rivi[0])]+list(map(lambda x: -float(x), rivi)))
            curs.execute('SELECT osoite,partitiivi,gluteenia,laktoosia,eikasvis,eivege FROM arvot;')
            for rivi in curs:
                osoitteet.append(rivi[0])
                nimet.append(rivi[1])
                gluteenia.append(rivi[2])
                laktoosia.append(rivi[3])
                lihaa.append(rivi[4])
                elainperainen.append(rivi[5])
    conn.close()
    c = hinnat(osoitteet)
    for i in reversed(range(len(c))):
        if c[i] is None or (gluteenia[i] and keliakia) or (laktoosia[i] and laktoosi) or (lihaa[i] and kasvis) or (elainperainen[i] and vege):
            del c[i]
            del A[i]
            del nimet[i]
            del osoitteet[i]

    A = t(A)

    if vege:
        del b[I_INDEKSI]
        del b[B12_INDEKSI]
        del b[DHA_INDEKSI]
        del A[I_INDEKSI]
        del A[B12_INDEKSI]
        del A[DHA_INDEKSI]
    try:
        res = linprog(c, A_ub=A, b_ub=b, method="revised simplex")
    except ValueError:
        return 0
    if not res.success:
        return 0
    return (nimet, res.x, res.fun, res.x * c, osoitteet)

@app.route('/aineet')
def aineet():
    nimetjaosoitteet = []
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    with conn:
        with conn.cursor() as curs:
            curs.execute('SELECT nimi, osoite FROM arvot;')
            for rivi in curs:
                nimetjaosoitteet.append({'nimi': rivi[0], 'osoite': ALKU+rivi[1]})
    conn.close()
    return render_template('aineet.html', data=nimetjaosoitteet)

@app.route('/',methods=['GET','POST'])
def index():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    IKARYHMAT = []
    with conn:
        with conn.cursor() as curs:
            curs.execute('SELECT ryhma FROM saannit;')
            for r in curs:
                IKARYHMAT.append(str(r[0]))
    conn.close()
    class HenkiloForm(FlaskForm):
        ika = SelectField('Ikä: ', choices=ryhmat2iat(IKARYHMAT))
        puoli = SelectField('Sukupuoli: ', choices=['Mies','Nainen'])
        energia = IntegerField('Energiantarve (kcal/päivä): ', validators=[DataRequired(), NumberRange(min=1)])
        keliakia = BooleanField('Keliakia')
        laktoosi = BooleanField('Laktoosi-intoleranssi')
        kasvis = BooleanField('Kasvissyönti')
        vege = BooleanField('Veganismi (Jos ruksaat, laskuri sivuuttaa DHA-rasvahapon, B12-vitamiinin ja jodin)')
        proteiini = IntegerField('Proteiinia (g/päivä)', validators=[Optional(), NumberRange(min=0)])
    form = HenkiloForm()
    tulos = []
    summa = 0
    if form.validate_on_submit():
        try:
            (nimet,maarat,summa,hinnat,osoitteet) = syote2tulos(request.form.get('ika'), request.form.get('puoli'),
                request.form.get('energia'), request.form.get('keliakia'), request.form.get('laktoosi'), request.form.get('kasvis'),
                request.form.get('vege'), request.form.get('proteiini'))
            for i in range(len(nimet)):
                grammoja = int(float(maarat[i])*100*7 + 0.5)
                if grammoja != 0:
                    tulos.append({'nimi': nimet[i], 'maara': str(grammoja), 'hinta': round(7*hinnat[i],2), 'osoite': ALKU+osoitteet[i]})
        except TypeError:
            tulos = 'Ei ratkaisua'
    return Response(render_template('etusivu.html', tulos=tulos, summa=round(summa*7,2), iat=ryhmat2iat(IKARYHMAT), puolet=["Mies","Nainen"], form=form))

if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0')