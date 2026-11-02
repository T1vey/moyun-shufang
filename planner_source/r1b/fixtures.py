"""Independent nominal drawing fixtures, not measured paper coordinates."""
import numpy as np


def drawings(model):
    # Anchor defines only a nominal paper origin; q0 below is independent and
    # not an inverse solution for the first waypoint.
    anchor=np.array([0.,-.5,1.,np.pi/2-.5,0.])
    t,_=model.evaluate(anchor)
    center=t[:3,3]
    q0=[.03,-.56,.98,1.02,0.]
    def line(a,b):
        return dict(type='line',start_m=(center+np.array(a)).tolist(),end_m=(center+np.array(b)).tolist())
    def circle(radius,sweep):
        return dict(type='arc',center_m=center.tolist(),u=[1,0,0],v=[0,1,0],radius_m=radius,start_rad=0.,sweep_rad=sweep)
    def spec(name,segments):
        return dict(name=name,units='m_rad',plane_origin_m=center.tolist(),plane_normal=[0,0,1],pen_axis=[0,0,-1],
                    strokes=[dict(segments=s) for s in segments],q0=q0,model_status='nominal_simulation_only')
    return [
        spec('line_20mm',[[line([-.01,0,0],[.01,0,0])]]),
        spec('circle_ccw_8mm',[[circle(.008,2*np.pi)]]),
        spec('circle_cw_8mm',[[circle(.008,-2*np.pi)]]),
        spec('corner',[[line([-.008,-.008,0],[.008,-.008,0]),line([.008,-.008,0],[.008,.008,0])]]),
        spec('two_strokes',[[line([-.008,-.006,0],[.008,-.006,0])],[line([.008,.006,0],[-.008,.006,0])]]),
        spec('holdout_circle_11mm',[[circle(.011,2*np.pi)]]),
        spec('holdout_reverse_line',[[line([.012,.007,0],[-.012,-.007,0])]]),
        spec('holdout_triangle',[[line([-.006,-.005,0],[.006,-.005,0]),line([.006,-.005,0],[0,.007,0]),line([0,.007,0],[-.006,-.005,0])]]),
    ]
