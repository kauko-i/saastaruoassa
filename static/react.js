const PAIVAA_VIIKOSSA = 7;
const GRAMMAA_HEHTOGRAMMASSA = 100;
const SENTTIA_EUROSSA = 100;

class Laskuri extends React.PureComponent {
    constructor(props) {
        super(props);
        this.paivitaState = this.paivitaState.bind(this);
        this.state = { viesti: '', lista: [], viikossa: '' };
    }

    paivitaState(uusi) {
        this.setState(uusi);
    }

    render() {
        return (<div>
            <HenkiloLomake paivitaState={this.paivitaState}></HenkiloLomake>
            {(this.state.viesti || this.state.lista.length != 0) &&
                <Tuloslista viesti={this.state.viesti} lista={this.state.lista} viikossa={this.state.viikossa}></Tuloslista>
            }
        </div>
        );
    }
}

class HenkiloLomake extends React.PureComponent {
    constructor(props) {
        super(props);
        const ikaryhmat = document.querySelector('#ryhmat').value.split(',');
        this.state = {
            ryhmat: ikaryhmat,
            sukupuoli: 'M',
            ika: ikaryhmat[0],
            keliakia: false,
            laktoosi: false,
            kasvis: false,
            vegaani: false
        };
        this.handleChange = this.handleChange.bind(this);
        this.handleSubmit = this.handleSubmit.bind(this);
    }

    handleChange(event) {
        const { target } = event;
        if (target.name == 'energia') {
            if (!target.value.match(/^[1-9]\d*$/))
                target.setCustomValidity('Syötä positiivinen tarve!');
            else
                target.setCustomValidity('');
        }
        this.setState({ [target.name]: target.type === 'checkbox' ? target.checked : target.value });
    }

    async handleSubmit(event) {
        event.preventDefault();
        fetch('/', {
            method: 'POST',
            headers: {
                'Content-type': 'application/json',
            },
            body: JSON.stringify({
                'ika': this.state.ika,
                'sukupuoli': this.state.sukupuoli,
                'energia': this.state.energia,
                'keliakia': this.state.keliakia,
                'laktoosi': this.state.laktoosi,
                'kasvis': this.state.kasvis,
                'vegaani': this.state.vegaani
            }),
        }).then((res) => res.json()).then((res) => {
            if (JSON.stringify(res) === '{}') {
                this.props.paivitaState({viesti: 'Vaatimukset täyttävää kokonaisuutta ei löydy...', lista: []});
            } else {
                this.props.paivitaState({viesti: '', lista: res.lista, viikossa: res.yhteensa});
            }
        });
        this.props.paivitaState({viesti: 'Luetaan hintoja...', lista: []});
    }

    render() {
        return (<form onSubmit={this.handleSubmit}>
            <fieldset>
                <label>Ikä:
                    <select name="ika" onChange={this.handleChange}>
                        {
                            this.state.ryhmat.map((ryhma, i) => {
                                if (i == this.state.ryhmat.length - 1)
                                    return <option key={ryhma} id={ryhma}>&gt;{ryhma}</option>;
                                return <option key={ryhma} id={ryhma}>{ryhma}-{Number(this.state.ryhmat[i + 1]) - 1}</option>;
                            })
                        }
                    </select>
                </label>
                <label>Sukupuoli:
                    <select name="sukupuoli" onChange={this.handleChange}>
                        <option id="M">Mies</option>
                        <option id="N">Nainen</option>
                    </select>
                </label>
                <label onChange={this.handleChange}>Energiantarve (kcal/päivä):
                    <input required name="energia" type="number"/>
                </label>
            </fieldset>
            <fieldset>
                <label>
                    <input name="keliakia"
                        onChange={this.handleChange}
                        type="checkbox"/>
                    Keliakia
                </label>
                <label>
                    <input name="laktoosi"
                        onChange={this.handleChange}
                        type="checkbox"/>
                    Laktoosi-intoleranssi
                </label>
                <label>
                    <input name="kasvis"
                        onChange={this.handleChange}
                        type="checkbox"/>
                    Kasvissyöjä
                </label>
                <label>
                    <input name="vegaani"
                        onChange={this.handleChange}
                        type="checkbox"/>
                    Vegaani
                </label>
            </fieldset>
            <input type="submit" value="Submit" />
        </form>);
    }
}

class Tuloslista extends React.PureComponent {
    constructor(props) {
        super(props);
    }

    render() {
        if (this.props.viesti)
            return <p>{this.props.viesti}</p>;
        return <div>
            <p>Tulokset (viikottainen määrä):</p>
            <ul>{
            this.props.lista.filter((aine) => aine.maara != 0).map(function (aine) {
                return <li key={aine.nimi}>{aine.nimi} {Math.round(aine.maara*PAIVAA_VIIKOSSA*GRAMMAA_HEHTOGRAMMASSA)} g <a href={''+aine.osoite}>({Math.round(aine.hinta*SENTTIA_EUROSSA*PAIVAA_VIIKOSSA)/SENTTIA_EUROSSA} €)</a></li>;
            })}
            </ul>
            <p>Yhteensä {Math.round(this.props.viikossa*SENTTIA_EUROSSA*PAIVAA_VIIKOSSA)/SENTTIA_EUROSSA} €/viikko!</p>
        </div>;
    }
}

ReactDOM.render(
    <Laskuri></Laskuri>,
    document.getElementById('root')
);
