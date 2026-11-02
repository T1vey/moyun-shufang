#include "ik_step.h"
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
static bool read(std::istream &in,float *v,int n) { for(int i=0;i<n;++i) if(!(in>>v[i])) return false; return true; }
int main(int argc,char **argv) {
    std::ifstream in(argc>1?argv[1]:"ik_vectors.txt");
    int n=0,failed=0; if(!(in>>n)||n<300) return 3;
    float q[5],p[3],axis[3],w[6],s[6],tool[3],ta[3],lim[10],mu,maxstep;
    float want[5],ewant[6],pwant,twant,dq[5],next[5],e[6],pe,te;
    unsigned int abi; int mode;
    for(int row=0;row<n;++row) {
        if(!(read(in,q,5)&&read(in,p,3)&&read(in,axis,3)&&read(in,w,6)&&read(in,s,6)&&
             read(in,tool,3)&&read(in,ta,3)&&read(in,lim,10)&&(in>>mu>>maxstep>>mode)&&
             read(in,want,5)&&read(in,ewant,6)&&(in>>pwant>>twant))) return 4;
        int st=z20_ik_step(q,p,axis,w,s,tool,ta,lim,mu,maxstep,mode,dq,next,e,&pe,&te,&abi);
        bool ok=st==0&&abi==0x534F0202u&&std::fabs(pe-pwant)<2e-6f&&std::fabs(te-twant)<2e-6f;
        for(int k=0;k<5;++k) ok=ok&&std::isfinite(dq[k])&&
            std::fabs(dq[k]-want[k])<=2e-5f+.005f*std::fabs(want[k])&&
            std::fabs(q[k]+dq[k]-next[k])<1e-6f&&std::fabs(dq[k])<=maxstep+2e-6f&&
            next[k]>=lim[2*k]-2e-6f&&next[k]<=lim[2*k+1]+2e-6f;
        for(int k=0;k<6;++k) ok=ok&&std::fabs(e[k]-ewant[k])<2e-6f;
        if(!ok) { ++failed; if(failed<6) std::cout<<"failed_vector="<<row<<" status="<<st<<"\n"; }
    }
    int st=z20_ik_step(q,p,axis,w,s,tool,ta,lim,-1,maxstep,mode,dq,next,e,&pe,&te,&abi);
    if(st!=1) ++failed;
    for(int k=0;k<5;++k) if(dq[k]!=0) ++failed;
    q[0]=std::numeric_limits<float>::quiet_NaN();
    st=z20_ik_step(q,p,axis,w,s,tool,ta,lim,mu,maxstep,mode,dq,next,e,&pe,&te,&abi);
    if(st!=1) ++failed;
    std::cout<<"IK_VECTOR_GATE cases="<<n<<" invalid=2 failed="<<failed<<"\n";
    return failed?1:0;
}
