"""Pen tracking assessment from calibrated joint feedback, in metres."""
import numpy as np
from motion import angles_from_counts


class TrackingMonitor:
    def __init__(self,machine):
        import planning
        from r1a.model import Model
        self.model=Model(machine['model']); self.machine=machine
        cfg=machine.get('tracking',{})
        self.tip_limit=float(cfg.get('max_tip_error_m',.002))
        self.normal_limit=float(cfg.get('max_normal_error_m',.001))
        from drawing_geometry import paper_frame
        self.normal=(paper_frame(machine['paper'])['normal']
            if (machine['paper'].get('xy_calibration') or {}).get('contact_plane_enabled')
            else np.asarray(machine['paper']['normal'],dtype=float))
        if (not np.isfinite([self.tip_limit,self.normal_limit]).all() or min(self.tip_limit,self.normal_limit)<=0
                or self.normal.shape!=(3,) or not np.isclose(np.linalg.norm(self.normal),1)):
            raise ValueError('invalid drawing tracking limits or paper normal')
        self.samples=0; self.max_tip=self.max_normal=self.max_source=0.
        self.max_axis_deg=0.; self.phases={}
    def observe(self,counts,command):
        if not command.get('pen_down'):
            return None
        row=self._measure(counts,command)
        tip,normal,source_error=row['tip_error_m'],row['normal_error_m'],row['source_path_error_m']
        if source_error is not None:self.max_source=max(self.max_source,source_error)
        self.samples+=1; self.max_tip=max(self.max_tip,tip); self.max_normal=max(self.max_normal,normal)
        self.max_axis_deg=max(self.max_axis_deg,row['pen_axis_error_deg'])
        return row
    def observe_phase(self,counts,command):
        row=self.observe(counts,command) if command.get('pen_down') else self._measure(counts,command)
        phase=command.get('phase','DRAW' if command.get('pen_down') else 'MOVE')
        stats=self.phases.setdefault(phase,dict(samples=0,max_tip_error_m=0.,max_normal_error_m=0.,max_pen_axis_error_deg=0.))
        stats['samples']+=1
        for key in ('tip_error_m','normal_error_m','pen_axis_error_deg'):
            stats['max_'+key]=max(stats['max_'+key],row[key])
        return row
    def _measure(self,counts,command):
        target=np.asarray(command.get('tip_reference_m',command['tip_target_m']),dtype=float)
        if target.shape!=(3,) or not np.isfinite(target).all():
            raise ValueError('invalid tracking reference')
        pose=self.model.pose(angles_from_counts(self.machine,counts))
        delta=pose[:3,3]-target
        tip=float(np.linalg.norm(delta)); normal=float(abs(delta@self.normal))
        source_error=None
        if 'segment_start_m' in command and 'segment_end_m' in command:
            start,end=[np.asarray(command[k],dtype=float) for k in ('segment_start_m','segment_end_m')]
            if start.shape!=(3,) or end.shape!=(3,) or not np.isfinite([start,end]).all():
                raise ValueError('invalid source segment')
            vector=end-start; length=float(vector@vector)
            ratio=float(np.clip((pose[:3,3]-start)@vector/length,0,1)) if length else 0.
            source_error=float(np.linalg.norm(pose[:3,3]-start-ratio*vector))
        axis=pose[:3,:3]@self.model.tool_axis
        wanted=np.asarray(command.get('axis_target',self.machine['paper'].get('pen_axis',-self.normal)),dtype=float)
        angle=float(np.degrees(np.arctan2(np.linalg.norm(np.cross(axis,wanted)),np.dot(axis,wanted))))
        return dict(tip_error_m=tip,normal_error_m=normal,source_path_error_m=source_error,
                    signed_normal_error_m=float(delta@self.normal),model_tip_m=pose[:3,3].tolist(),
                    model_pen_axis=axis.tolist(),pen_axis_error_deg=angle,
                    qualified=bool(tip<=self.tip_limit and normal<=self.normal_limit))
    def summary(self):
        return dict(scope='calibrated_fk_from_encoder_feedback',samples=self.samples,
            tracking_qualified=bool(self.samples and self.max_tip<=self.tip_limit and self.max_normal<=self.normal_limit),
            max_tip_error_m=self.max_tip,max_normal_error_m=self.max_normal,
            max_source_path_error_m=self.max_source,
            tip_limit_m=self.tip_limit,normal_limit_m=self.normal_limit,
            max_pen_axis_error_deg=self.max_axis_deg,phases=self.phases)
