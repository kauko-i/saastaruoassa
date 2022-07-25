from flask import Flask, Response, render_template, request
from flask_caching import Cache
import re
from scipy.optimize import linprog
import os
import psycopg2
from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, IntegerField
from wtforms.validators import DataRequired, NumberRange, Optional
from flask_wtf.csrf import CSRFProtect
import asyncio
import aiohttp

# Välimuistin asetukset
config = {
    "DEBUG": False,
    "CACHE_TYPE": "SimpleCache",
}

# Alusta sovellus.
app = Flask(__name__)
app.config.from_mapping(config)
app.secret_key = os.environ['SECRET_KEY']
CSRFProtect(app)
cache = Cache(app)

# Ohjelmaa koskevat vakiot
JOULEA_KALORISSA = 4.18
RASVAN_ENERGIA = 0.037
PROTEIININ_ENERGIA = 0.017
DATABASE_URL = os.environ['DATABASE_URL']
ENERGIA_YLARAJA = 1.001
MILLIGRAMMAA_PER_GRAMMA = 1000
I_INDEKSI = 27
B12_INDEKSI = 17
DHA_INDEKSI = 9
SUKUPUOLET = ['Mies, Nainen']

# Transpoosifunktio: tietokannassa ruoka-aineet vastaavat rivejä, mutta laskennassa niiden on vastattava sarakkeita.
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

'''
Muuntaa tietokannan käyttämät ryhmätunnukset (sukupuoli+alkuvuosi) käyttäjältä kysyttävään ikäryhmämuotoon 
(alkuvuosi-loppuvuosi tai >alkuvuosi korkeimmalle).
'''
def ryhmat2iat(ryhmat):
    tuplatpois = sorted(list(map(lambda x: x[1:], filter(lambda x: 'N' not in x, ryhmat))),key=int)
    palaute = map(lambda i: '{}-{}'.format(tuplatpois[i], int(tuplatpois[i + 1]) - 1) if i < len(tuplatpois) - 1 else '>{}'.format(tuplatpois[i]), range(len(tuplatpois)))
    return sorted(palaute, key=lambda x: int(x.split('-')[0].replace('>', '')))

# Hinnanlukua koskevat vakiot
ALKU = "https://www.s-kaupat.fi/tuote/"
HINTAPAATTEET = [" €/kg", " €/l"]

'''
Hakee ruoka-aineiden ilmoitetut keskihinnat Prismoissa ja tallentaa ne välimuistiin.
Listaan tulee None, jos tietokannan osoitteella ei löydy vastaavaa tuotetta.
Palautetaan lista, jossa indeksi i vastaa osoitteesta i löytyvää hintaa.
'''
@cache.cached(timeout=86400)
def hinnat(osoitteet):
    async def hinnatNoCache(osoitteet):
        hintadict = {}
        async def hinta(osoite):
            async with aiohttp.ClientSession() as session:
                async with session.get(ALKU+osoite) as response:
                    html = await response.text()
                    hinta = None
                    for i in range(len(HINTAPAATTEET)):
                        hinta = re.search("\d*,\d*{}".format(HINTAPAATTEET[i]), html)
                        if hinta:
                            hinta = hinta.group(0)[:-len(HINTAPAATTEET[i])]
                            break
                    hintadict[osoite] = None if hinta is None else float(hinta.replace(',', '.'))/10
        tasks = []
        for osoite in osoitteet:
             tasks.append(asyncio.create_task(hinta(osoite)))
        for task in tasks:
            await task
        return list(map(lambda x: hintadict[x], osoitteet))
    return asyncio.run(hinnatNoCache(osoitteet))

'''
Muuntaa käyttäjän antaman syötteen käyttäjälle näytettäväksi tulokseksi.
Parametrit ovat samat kuin lomakkeella.
'''
def syote2tulos(ika, sukupuoli, energia, keliakia, laktoosi, kasvis, vege, proteiini):
    # Lomake käyttää kilokaloreita, tietokannat jouleja.
    energia = int(energia)*JOULEA_KALORISSA

    # Tietokanta yksilöi ikäryhmät alarajan perusteella.
    ika = ''.join(filter(str.isdigit, ika.split('-')[0]))

    # Muodosta b-vektori ja A-matriisi. Vaikutti, että energiansaantivaatimuksen ei pidä olla aivan tarkka, jottei laskenta sekoaisi.
    b = [ENERGIA_YLARAJA*energia,-energia]
    A = []
    # Seuraavissa 6 taulukossa indeksit vastaavat matriisin A rivejä (myöhemmin sarakkeita).
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
            # Hae proteiinien prosentteina annettu suositus ja laske milligrammamäärä, tai käytä käyttäjän syötettä.
            if not proteiini:
                curs.execute('SELECT proteiini FROM saannit WHERE ryhma = %s;', (ryhma,))
                for rivi in curs:
                    b.append(-float(str(rivi[0])[:-1])/100*energia/PROTEIININ_ENERGIA)
            else:
                b.append(-int(proteiini)*MILLIGRAMMAA_PER_GRAMMA)
            # Hae milligrammoina annetut suositukset.
            curs.execute('SELECT dha,kuitu,a,b1,b2,b3,b6,b9,b12,c,d,e,ca,p,k,mg,fe,zn,i,se FROM saannit WHERE ryhma = %s', (ryhma,))
            for rivi in curs:
                for i in range(len(rivi)):
                    b.append(-float(rivi[i]))

            # Hae ravintoarvot.
            curs.execute('''SELECT energia,rasva,kertarasva,monirasva,n3,alfa,linoli,proteiini,
                        dha,kuitu,a,b1,b2,b3,b6,b9,b12,c,d,e,ca,p,k,mg,fe,zn,i,se FROM arvot ORDER BY nimi;''')
            for rivi in curs:
                A.append([float(rivi[0])]+list(map(lambda x: -float(x), rivi)))
            # Hae ruokien tuoteosoitteet, partitiivimuodon nimet ja se, poissulkeeko kukin eritysiruokavalio sen.
            curs.execute('SELECT osoite,partitiivi,gluteenia,laktoosia,eikasvis,eivege FROM arvot ORDER BY nimi;')
            for rivi in curs:
                osoitteet.append(rivi[0])
                nimet.append(rivi[1])
                gluteenia.append(rivi[2])
                laktoosia.append(rivi[3])
                lihaa.append(rivi[4])
                elainperainen.append(rivi[5])
    conn.close()
    c = hinnat(osoitteet)
    # Poista ne tuotteet laskuista, jotka erityisruokavalio poissulkee tai joille ei löytynyt hintaa.
    for i in reversed(range(len(c))):
        if c[i] is None or (gluteenia[i] and keliakia) or (laktoosia[i] and laktoosi) or (lihaa[i] and kasvis) or (elainperainen[i] and vege):
            del c[i]
            del A[i]
            del nimet[i]
            del osoitteet[i]

    # Muuta A transpoosikseen.
    A = t(A)

    # Vegaaniruokavalion laskenta vaatii, että tietyt ravintoaineet jätetään huomiotta.
    if vege:
        del b[I_INDEKSI]
        del b[B12_INDEKSI]
        del b[DHA_INDEKSI]
        del A[I_INDEKSI]
        del A[B12_INDEKSI]
        del A[DHA_INDEKSI]
    # Varsinainen laskenta
    try:
        res = linprog(c, A_ub=A, b_ub=b, method="revised simplex")
    except ValueError:
        return 0
    if not res.success:
        return 0
    return (nimet, res.x, res.fun, res.x * c, osoitteet)

# Hakee tietokannasta ruoka-aineiden nimet ja tuoteosoitteet käyttäjälle näytettäväksi.
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

# Etusivun näyttävä "pääohjelma"
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
    return Response(render_template('etusivu.html', tulos=tulos, summa=round(summa*7,2), puolet=SUKUPUOLET, form=form))

if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0')