#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
using M=std::array<double,16>;
using V=std::array<double,3>;
static M eye(){M a{};a[0]=a[5]=a[10]=a[15]=1;return a;}
static M mul(const M&a,const M&b){
#ifdef __SYNTHESIS__
#pragma HLS INLINE off
#pragma HLS ALLOCATION operation instances=dmul limit=1
#pragma HLS ALLOCATION operation instances=dadd limit=1
#endif
M c{};for(int i=0;i<4;i++)for(int j=0;j<4;j++)for(int k=0;k<4;k++)c[i*4+j]+=a[i*4+k]*b[k*4+j];return c;}
static V cross(V a,V b){return {{a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]}};}
static double norm(V a){return std::sqrt(a[0]*a[0]+a[1]*a[1]+a[2]*a[2]);}
static M rot(V a,double q){M r=eye();double c=std::cos(q),s=std::sin(q);for(int i=0;i<3;i++)for(int j=0;j<3;j++)r[i*4+j]=(i==j?c:0)+(1-c)*a[i]*a[j];r[1]-=s*a[2];r[2]+=s*a[1];r[4]+=s*a[2];r[6]-=s*a[0];r[8]-=s*a[1];r[9]+=s*a[0];return r;}
static bool finite(const double*p,int n){for(int i=0;i<n;i++)if(!std::isfinite(p[i]))return false;return true;}
// Model row = 16-value fixed parent transform, 3-value local axis, lower, upper.
static M fk7(const double*m,const double*q,const double*tool,double*j,double*frames,bool want_j,bool want_frames){
#ifdef __SYNTHESIS__
#pragma HLS INLINE off
#pragma HLS ALLOCATION operation instances=dmul limit=1
#pragma HLS ALLOCATION operation instances=dadd limit=1
#pragma HLS ALLOCATION operation instances=dsub limit=1
#endif

    M t=eye();V axes[7],origins[7];
    if(want_frames)for(int n=0;n<16;n++)frames[n]=t[n];
    for(int k=0;k<7;k++){
        M origin;for(int n=0;n<16;n++)origin[n]=m[21*k+n];t=mul(t,origin);
        V axis{{m[k*21+16],m[k*21+17],m[k*21+18]}};
        for(int i=0;i<3;i++){origins[k][i]=t[i*4+3];axes[k][i]=0;for(int c=0;c<3;c++)axes[k][i]+=t[i*4+c]*axis[c];}
        t=mul(t,rot(axis,q[k]));if(want_frames)for(int n=0;n<16;n++)frames[(k+1)*16+n]=t[n];
    }
    M tcp;for(int n=0;n<16;n++)tcp[n]=tool[n];t=mul(t,tcp);
    if(want_j)for(int k=0;k<7;k++){
        V delta{{t[3]-origins[k][0],t[7]-origins[k][1],t[11]-origins[k][2]}};
        V v=cross(axes[k],delta);for(int i=0;i<3;i++){j[i*7+k]=v[i];j[(i+3)*7+k]=axes[k][i];}
    }
    return t;
}
#ifndef __SYNTHESIS__
static M fk(const double*m,const double*q,const double*tool,double*j=nullptr,double*frames=nullptr){
    double unused_j[42],unused_frames[128];
    return fk7(m,q,tool,j?j:unused_j,frames?frames:unused_frames,j!=nullptr,frames!=nullptr);
}
#endif
static V logRotation(const M&target,const M&current){
#ifdef __SYNTHESIS__
#pragma HLS INLINE off
#pragma HLS ALLOCATION operation instances=dmul limit=1
#pragma HLS ALLOCATION operation instances=dadd limit=1
#pragma HLS ALLOCATION operation instances=dsub limit=1
#pragma HLS ALLOCATION operation instances=ddiv limit=1
#endif

    double r[3][3]{};for(int i=0;i<3;i++)for(int j=0;j<3;j++)for(int k=0;k<3;k++)r[i][j]+=target[i*4+k]*current[j*4+k];
    double angle=std::acos(std::max(-1.,std::min(1.,(r[0][0]+r[1][1]+r[2][2]-1)*.5)));
    V v{{r[2][1]-r[1][2],r[0][2]-r[2][0],r[1][0]-r[0][1]}};
    if(angle<1e-7){for(double&x:v)x*=.5;return v;}
    if(3.141592653589793-angle<1e-4){
        int k=0;for(int i=1;i<3;i++)if(r[i][i]>r[k][k])k=i;
        V a{};a[k]=std::sqrt(std::max(0.,(r[k][k]+1)*.5));
        if(a[k]<1e-8)return {{angle,0,0}};
        for(int i=0;i<3;i++)if(i!=k)a[i]=(r[i][k]+r[k][i])/(4*a[k]);
        double n=norm(a);for(double&x:a)x*=angle/n;return a;
    }
    for(double&x:v){x*=angle/(2*std::sin(angle));}
    return v;
}
static double error(const M&t,const M&cur,double*e,double w){
    V r=logRotation(t,cur);double cost=0;for(int i=0;i<3;i++){e[i]=t[i*4+3]-cur[i*4+3];e[i+3]=r[i];cost+=e[i]*e[i]+w*w*r[i]*r[i];}return cost;
}
static bool linear(double a[7][7],double*b,double*x){
#ifdef __SYNTHESIS__
#pragma HLS INLINE off
#pragma HLS ALLOCATION operation instances=dmul limit=1
#pragma HLS ALLOCATION operation instances=dadd limit=1
#pragma HLS ALLOCATION operation instances=dsub limit=1
#pragma HLS ALLOCATION operation instances=ddiv limit=1
#endif

    for(int k=0;k<7;k++){
        int p=k;for(int i=k+1;i<7;i++)if(std::abs(a[i][k])>std::abs(a[p][k]))p=i;
        if(std::abs(a[p][k])<1e-18)return false;
        for(int j=k;j<7;j++){std::swap(a[k][j],a[p][j]);}
        std::swap(b[k],b[p]);
        for(int i=k+1;i<7;i++){double f=a[i][k]/a[k][k];for(int j=k;j<7;j++)a[i][j]-=f*a[k][j];b[i]-=f*b[k];}
    }
    for(int i=6;i>=0;i--){double s=b[i];for(int j=i+1;j<7;j++)s-=a[i][j]*x[j];x[i]=s/a[i][i];}return finite(x,7);
}
static int solve7(const double*m,const double*tool,const double*target,const double*seed,const double*reference,const double*opt,double*out,double*stats){
#ifdef __SYNTHESIS__
#pragma HLS INLINE
#endif

    if(!finite(m,147)||!finite(tool,16)||!finite(target,16)||!finite(seed,7)||!finite(reference,7)||!finite(opt,7))return -1;
    M t;for(int n=0;n<16;n++)t[n]=target[n];for(int n=0;n<7;n++)out[n]=seed[n];
    for(int i=0;i<7;i++)if(out[i]<m[21*i+19]||out[i]>m[21*i+20])return -2;
    if(opt[0]<=0||opt[1]<=0||opt[2]<1||opt[2]>1000||opt[3]<=0||opt[4]<=0||opt[5]<=0||opt[6]<0)return -1;
    double unused_frames[128],unused_j[42];
    for(int it=0;it<1000;it++){
        if(it>=int(opt[2]))break;
        double j[42],e[6];M cur=fk7(m,out,tool,j,unused_frames,true,false);double cost=error(t,cur,e,opt[4]);
        stats[0]=std::sqrt(e[0]*e[0]+e[1]*e[1]+e[2]*e[2]);stats[1]=std::sqrt(e[3]*e[3]+e[4]*e[4]+e[5]*e[5]);stats[2]=it;
        if(stats[0]<=opt[0]&&stats[1]<=opt[1])return 0;
        double a[7][7]{},b[7]{},dq[7]{};
        for(int k=0;k<7;k++){
            for(int l=0;l<7;l++)for(int r=0;r<6;r++)a[k][l]+=j[r*7+k]*j[r*7+l]*(r<3?1:opt[4]*opt[4]);
            for(int r=0;r<6;r++)b[k]+=j[r*7+k]*e[r]*(r<3?1:opt[4]*opt[4]);
            a[k][k]+=opt[5]*opt[5]+opt[6];b[k]+=opt[6]*(reference[k]-out[k]);
        }
        if(!linear(a,b,dq))return 3;
        double maxd=0;for(double d:dq)maxd=std::max(maxd,std::abs(d));
        double scale=maxd>opt[3]?opt[3]/maxd:1;
        bool improved=false;
        for(int back=0;back<16;back++,scale*=.5){
            double trial[7];for(int k=0;k<7;k++)trial[k]=std::max(m[21*k+19],std::min(m[21*k+20],out[k]+scale*dq[k]));
            double te[6];double next=error(t,fk7(m,trial,tool,unused_j,unused_frames,false,false),te,opt[4]);
            if(next<cost){for(int n=0;n<7;n++)out[n]=trial[n];improved=true;break;}
        }
        if(!improved)return 2;
    }
    double e[6];error(t,fk7(m,out,tool,unused_j,unused_frames,false,false),e,opt[4]);stats[0]=std::sqrt(e[0]*e[0]+e[1]*e[1]+e[2]*e[2]);stats[1]=std::sqrt(e[3]*e[3]+e[4]*e[4]+e[5]*e[5]);return 1;
}
