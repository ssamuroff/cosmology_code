include ${COSMOSIS_SRC_DIR}/config/compilers.mk

USER_CFLAGS= -I ../limber -I ${GSL_INC}
USER_LDFLAGS= -L../limber -llimber -lcosmosis -L ${GSL_LIB} -lgsl -lgslcblas 

all: interface.so

interface.so: shear_shear.c interface.c ../limber/liblimber.a
	$(CC) $(CFLAGS)  -shared -o interface.so shear_shear.c interface.c $(LDFLAGS)

clean:
	rm -rf interface.so interface.so.dSYM

test:
	@echo Alas, shear/spectra has no tests

