from app import create_app, db
from app.models import Maintenance, Circuit, Provider, MaintCircuit, MaintUpdate

app = create_app()


@app.shell_context_processor
def make_shell_context():
    return {
        'db': db,
        'Maintenance': Maintenance,
        'Provider': Provider,
        'MaintCircuit': MaintCircuit,
        'Circuit': Circuit,
        'MaintUpdate': MaintUpdate,
    }
