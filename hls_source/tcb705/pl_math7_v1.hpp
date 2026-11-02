#pragma once
// 1013 run_row pattern: one shared evaluation site for current/trial/FK rows.
// Nominal TCB705 URDF uses local +/-Z axes; fixed joint transforms stay in DDR.
#include <cmath>
#include <algorithm>
static bool finite(const double*p,int n){for(int i=0;i<n;i++)if(!std::isfinite(p[i]))return false;return true;}
static void matrix_product(const double a[16],const double b[16],double c[16]){
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=a complete dim=1
#pragma HLS ARRAY_PARTITION variable=b complete dim=1
    for(int i=0;i<4;i++)for(int j=0;j<4;j++){
#pragma HLS PIPELINE II=1
        double value=0;for(int k=0;k<4;k++)value+=a[4*i+k]*b[4*k+j];c[4*i+j]=value;
    }
}
static void geometry7(const double*m,const double*q,const double*tool,double*pose,double j[6][7]){
#pragma HLS INLINE off
#pragma HLS ALLOCATION operation instances=dmul limit=2
#pragma HLS ALLOCATION operation instances=dadd limit=1
#pragma HLS ALLOCATION operation instances=dsub limit=1
    double t[16]={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1},origins[7][3],axes[7][3];
    for(int joint=0;joint<8;joint++){
        double local[16],next[16];
        for(int i=0;i<16;i++)local[i]=joint<7?m[joint*21+i]:tool[i];
        matrix_product(t,local,next);
        for(int i=0;i<16;i++)t[i]=next[i];
        if(joint<7){
            double sign=m[joint*21+18],c=std::cos(q[joint]),s=std::sin(q[joint])*sign;
            for(int r=0;r<3;r++){
                origins[joint][r]=t[r*4+3];axes[joint][r]=t[r*4+2]*sign;
                double x=t[r*4],y=t[r*4+1];t[r*4]=c*x+s*y;t[r*4+1]=-s*x+c*y;
            }
        }
    }
    for(int i=0;i<16;i++)pose[i]=t[i];
    for(int k=0;k<7;k++)for(int r=0;r<3;r++){
        int a=(r+1)%3,b=(r+2)%3;
        j[r][k]=axes[k][a]*(t[b*4+3]-origins[k][b])-axes[k][b]*(t[a*4+3]-origins[k][a]);
        j[r+3][k]=axes[k][r];
    }
}
static bool direction7(double j[6][7],const double*e,const double*q,const double*reference,const double*o,double*dq){
#pragma HLS INLINE off
#pragma HLS ALLOCATION operation instances=dmul limit=2
#pragma HLS ALLOCATION operation instances=dadd limit=1
#pragma HLS ALLOCATION operation instances=dsub limit=1
#pragma HLS ALLOCATION operation instances=ddiv limit=1
#pragma HLS ALLOCATION operation instances=dsqrt limit=1
    double lower[7][7]={},b[7],y[7];
    for(int i=0;i<7;i++){
        double rhs=0;for(int r=0;r<6;r++)rhs+=j[r][i]*e[r]*(r<3?1:o[4]*o[4]);
        b[i]=rhs+o[6]*(reference[i]-q[i]);
        for(int k=0;k<=i;k++){
            double value=0;for(int r=0;r<6;r++)value+=j[r][i]*j[r][k]*(r<3?1:o[4]*o[4]);
            if(i==k)value+=o[5]*o[5]+o[6];
            for(int r=0;r<k;r++)value-=lower[i][r]*lower[k][r];
            if(i==k){if(!(value>0))return false;lower[i][k]=std::sqrt(value);}
            else lower[i][k]=value/lower[k][k];
        }
    }
    for(int i=0;i<7;i++){double value=b[i];for(int k=0;k<i;k++)value-=lower[i][k]*y[k];y[i]=value/lower[i][i];}
    for(int reverse=0;reverse<7;reverse++){int i=6-reverse;double value=y[i];for(int k=i+1;k<7;k++)value-=lower[k][i]*dq[k];dq[i]=value/lower[i][i];}
    return finite(dq,7);
}
static int run_row7(bool fk_only,const double*m,const double*tool,const double*target,const double*seed,const double*o,double*out,double*stats,double*pose){
#pragma HLS INLINE off
#pragma HLS ALLOCATION function instances=geometry7 limit=1
#pragma HLS ALLOCATION operation instances=dmul limit=2
#pragma HLS ALLOCATION operation instances=dadd limit=1
#pragma HLS ALLOCATION operation instances=dsub limit=1
#pragma HLS ALLOCATION operation instances=ddiv limit=1
#pragma HLS ALLOCATION operation instances=dsqrt limit=1
    double q[7],trial[7],dq[7]={0},gain=1,previous_cost=0;
    bool searching=false;int iteration=0,backtrack=0;
    for(int k=0;k<7;k++){q[k]=seed[k];out[k]=seed[k];}
    for(int evaluation=0;evaluation<17001;evaluation++){
        double current[7],j[6][7],error[6];
        for(int k=0;k<7;k++)current[k]=searching?trial[k]:q[k];
        geometry7(m,current,tool,pose,j); // sole geometry call site, including FK_ROWS
        if(fk_only)return finite(pose,16)?0:2;
        double relative[9];
        for(int r=0;r<3;r++)for(int c=0;c<3;c++){
            double v=0;for(int k=0;k<3;k++)v+=target[r*4+k]*pose[c*4+k];relative[r*3+c]=v;
        }
        // First-attempt local solver only. Large orientation changes are handed
        // back to the full CPU SO(3) solver, never accepted using a small-angle model.
        if(relative[0]+relative[4]+relative[8]<2.9975)return 2;
        error[3]=.5*(relative[7]-relative[5]);error[4]=.5*(relative[2]-relative[6]);error[5]=.5*(relative[3]-relative[1]);
        double pe2=0,ae2=0;
        for(int r=0;r<3;r++){error[r]=target[r*4+3]-pose[r*4+3];pe2+=error[r]*error[r];ae2+=error[r+3]*error[r+3];}
        double cost=pe2+o[4]*o[4]*ae2;
        if(!std::isfinite(cost))return 2;
        if(searching){
            if(cost<previous_cost){for(int k=0;k<7;k++){q[k]=trial[k];out[k]=q[k];}searching=false;iteration++;}
            else{backtrack++;gain*=.5;if(backtrack>=16)return 2;}
        }else{
            stats[0]=std::sqrt(pe2);stats[1]=std::sqrt(ae2);stats[2]=iteration;
            if(stats[0]<=o[0]&&stats[1]<=o[1])return 0;
            if(iteration>=int(o[2]))return 1;
            if(!direction7(j,error,q,seed,o,dq))return 2;
            double largest=0;for(int k=0;k<7;k++)largest=std::max(largest,std::abs(dq[k]));
            gain=largest>o[3]?o[3]/largest:1;previous_cost=cost;backtrack=0;searching=true;
        }
        if(searching)for(int k=0;k<7;k++)trial[k]=std::max(m[21*k+19],std::min(m[21*k+20],q[k]+gain*dq[k]));
    }
    return 1;
}
