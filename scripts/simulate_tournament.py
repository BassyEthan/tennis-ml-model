from src.sim.tournament import main

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--bracket', required=True)
    p.add_argument('--model', default='models/rf_model.pkl')
    a=p.parse_args()
    main(a.bracket, a.model)
