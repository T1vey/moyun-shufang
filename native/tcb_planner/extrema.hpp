#pragma once
// Bounded degree-five polynomial extrema on [0,1]. Derivative roots split the
// interval into monotone pieces, so each sign-changing piece has one root.
// Repeated roots are explicitly tested at derivative critical points.
#include <cmath>
#include <limits>
#include <algorithm>
static double poly(const double*c,int n,double u){double v=c[n];for(int i=n-1;i>=0;i--)v=v*u+c[i];return v;}
static int unit_roots(const double*c,int n,double*out){
    while(n>0&&c[n]==0)n--;
    if(n==0)return 0;
    if(n==1){double r=-c[0]/c[1];if(r>0&&r<1){out[0]=r;return 1;}return 0;}
    double d[5],critical[32],points[34];for(int i=1;i<=n;i++)d[i-1]=c[i]*i;
    int nc=unit_roots(d,n-1,critical);points[0]=0;for(int i=0;i<nc;i++)points[i+1]=critical[i];points[nc+1]=1;
    double scale=0;for(int i=0;i<=n;i++)scale+=std::abs(c[i]);
    const double tol=64*std::numeric_limits<double>::epsilon()*scale;
    double candidates[68];int count=0;
    for(int i=1;i<=nc;i++)if(std::abs(poly(c,n,points[i]))<=tol)candidates[count++]=points[i];
    for(int i=0;i<=nc;i++){
        double lo=points[i],hi=points[i+1],a=poly(c,n,lo),b=poly(c,n,hi);
        if((a<0&&b>0)||(a>0&&b<0)){
            for(int k=0;k<64;k++){double mid=(lo+hi)*.5,v=poly(c,n,mid);if(v==0){lo=hi=mid;break;}if((a<0&&v<0)||(a>0&&v>0)){lo=mid;a=v;}else hi=mid;}
            candidates[count++]=(lo+hi)*.5;
        }
    }
    std::sort(candidates,candidates+count);int used=0;
    for(int i=0;i<count;i++)if(used==0||candidates[i]-out[used-1]>1e-12){
        // Include near-zero critical probes too; do not truncate later roots.
        // Degree <=4 bounds the recursive candidate count by 2^4-1.
        out[used++]=candidates[i];
    }
    return used;
}
static void bounds(const double*c,int n,double*out){
    double d[5],roots[32];for(int i=1;i<=n;i++)d[i-1]=c[i]*i;
    int count=unit_roots(d,n-1,roots);double a=poly(c,n,0),b=poly(c,n,1),lo=std::min(a,b),hi=std::max(a,b),scale=0;
    for(int i=0;i<count;i++){double v=poly(c,n,roots[i]);lo=std::min(lo,v);hi=std::max(hi,v);}
    for(int i=0;i<=n;i++)scale+=std::abs(c[i]);
    double pad=128*std::numeric_limits<double>::epsilon()*scale;
    out[0]=std::max(std::abs(lo),std::abs(hi))+pad;out[1]=lo-pad;out[2]=hi+pad;
}
