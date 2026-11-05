CXX = g++
CPPFLAGS = -I.
CXXFLAGS = -O3 -std=c++17 -Wall -Wextra -Wpedantic -pthread
OPENMP_FLAGS = -fopenmp
VECTOR_FLAGS = -fopt-info-vec-optimized
PYTHON = python3

# Local correctness checks on macOS use Apple Clang + Homebrew libomp.
# The Linux build keeps g++ and -fopenmp with no extra dependencies.
ifeq ($(shell uname -s),Darwin)
CXX = clang++
LIBOMP_PREFIX ?= $(shell brew --prefix libomp)
CPPFLAGS += -I$(LIBOMP_PREFIX)/include
OPENMP_FLAGS = -Xpreprocessor -fopenmp
LDFLAGS += -L$(LIBOMP_PREFIX)/lib -Wl,-rpath,$(LIBOMP_PREFIX)/lib
LDLIBS += -lomp
VECTOR_FLAGS = -Rpass=loop-vectorize -Rpass-missed=loop-vectorize
endif

COMMON = ivf_io.cpp ivf_search.cpp ivf_student.cpp ivf_profile.cpp
HEADERS = ivf_io.h ivf_search.h ivf_profile.h

.PHONY: all test smoke vector-report clean
all: ivf_lab

ivf_lab: ivf_lab.cpp $(COMMON) $(HEADERS)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(OPENMP_FLAGS) ivf_lab.cpp $(COMMON) $(LDFLAGS) $(LDLIBS) -o $@

ivf_tests: tests/ivf_tests.cpp $(COMMON) $(HEADERS)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(OPENMP_FLAGS) tests/ivf_tests.cpp $(COMMON) $(LDFLAGS) $(LDLIBS) -o $@

ivf_student_tests: tests/ivf_student_tests.cpp $(COMMON) $(HEADERS)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(OPENMP_FLAGS) tests/ivf_student_tests.cpp $(COMMON) $(LDFLAGS) $(LDLIBS) -o $@

test: ivf_tests ivf_student_tests
	./ivf_tests
	./ivf_student_tests

smoke: ivf_lab
	$(PYTHON) tests/smoke_cli.py --binary ./ivf_lab
	$(PYTHON) tests/experiment_modes.py --binary ./ivf_lab

vector-report: ivf_student.cpp ivf_search.cpp $(HEADERS)
	mkdir -p build
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(OPENMP_FLAGS) $(VECTOR_FLAGS) -c ivf_student.cpp -o build/ivf_student.o 2> build/vectorization.txt
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(OPENMP_FLAGS) $(VECTOR_FLAGS) -c ivf_search.cpp -o build/ivf_search.o 2>> build/vectorization.txt
	@echo "Vectorization evidence: build/vectorization.txt"

clean:
	rm -f ivf_lab ivf_tests ivf_student_tests
