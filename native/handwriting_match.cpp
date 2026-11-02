#include <algorithm>
#include <cmath>
#include <limits>
#ifdef _WIN32
#define EXPORT extern "C" __declspec(dllexport)
#else
#define EXPORT extern "C"
#endif
EXPORT double hw_dtw(const double* a, const double* b) {
    double prev[65], row[65];
    std::fill(prev,prev+65,std::numeric_limits<double>::infinity()); prev[0]=0;
    for(int i=1;i<=64;++i) {
        std::fill(row,row+65,std::numeric_limits<double>::infinity());
        for(int j=std::max(1,i-8);j<=std::min(64,i+8);++j) {
            const double dx=a[2*(i-1)]-b[2*(j-1)],dy=a[2*(i-1)+1]-b[2*(j-1)+1];
            row[j]=std::sqrt(dx*dx+dy*dy)+std::min(prev[j],std::min(row[j-1],prev[j-1]));
        }
        std::copy(row,row+65,prev);
    }
    return prev[64]/64.;
}
