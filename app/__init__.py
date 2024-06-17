from flask import Flask, g, redirect, request, url_for
from flask_babel import Babel
from flask_caching import Cache


config = {
    "DEBUG": False,
    "CACHE_TYPE": "SimpleCache",
    "CORS_HEADERS": "application/json",
    "LANGUAGES": ["en", "fi"]
}

# Alusta sovellus.
app = Flask(__name__)
app.config.from_mapping(config)
cache = Cache(app)
babel = Babel(app)


from app.blueprints.multilingual import multilingual

app.register_blueprint(multilingual)

def get_locale():
    if not g.get('lang_code', None):
        g.lang_code = 'en'
    return g.lang_code

babel.init_app(app, locale_selector=get_locale)

@app.route('/')
def home():
    g.lang_code = request.accept_languages.best_match(app.config['LANGUAGES'])
    if not g.lang_code:
        g.lang_code = 'en'
    return redirect(url_for('multilingual.index'))

if __name__ == '__main__':
    app.debug = True
    if not g.lang_code:
        get_locale()
    app.run(host='0.0.0.0')
