import numpy as np
np.random.seed(1022019)
vec = np.random.rand(8)*8
np.savetxt('blind_params.txt',vec)
