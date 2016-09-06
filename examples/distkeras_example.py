import numpy as np

from keras.models import Sequential
from keras.models import model_from_json
from keras.layers.core import Dense, Dropout, Activation
from keras.optimizers import SGD
from keras.optimizers import RMSprop
from keras.utils import np_utils
from keras.utils.np_utils import to_categorical

from pyspark import SparkContext
from pyspark import SparkConf
from pyspark import SQLContext

from pyspark.ml.feature import StandardScaler
from pyspark.ml.feature import VectorAssembler
from pyspark.ml.feature import StringIndexer

from distkeras.distributed import EnsembleTrainer
from distkeras.distributed import LabelVectorTransformer
from distkeras.distributed import ModelPredictor

import os

# Setup Spark, and use the Databricks CSV loader.
os.environ['PYSPARK_SUBMIT_ARGS'] = "--packages com.databricks:spark-csv_2.10:1.4.0 pyspark-shell"
# Setup the Spark -, and SQL Context (note: this is for Spark < 2.0.0)
sc = SparkContext(appName="DistKeras ATLAS Higgs example")
sqlContext = SQLContext(sc)

# Read the Higgs dataset.
dataset = sqlContext.read.format('com.databricks.spark.csv')\
                    .options(header='true', inferSchema='true').load("data/atlas_higgs.csv");
# Print the schema of the dataset.
dataset.printSchema()
# Vectorize the features into the features column.
features = dataset.columns
features.remove('EventId')
features.remove('Weight')
features.remove('Label')
assembler = VectorAssembler(inputCols=features, outputCol="features")
dataset = assembler.transform(dataset)
# Since the output layer will not be able to read the string label, convert it to an double.
labelIndexer = StringIndexer(inputCol="Label", outputCol="label_index").fit(dataset)
dataset = labelIndexer.transform(dataset)
# Feature normalization.
standardScaler = StandardScaler(inputCol="features", outputCol="features_normalized", withStd=True, withMean=True)
standardScalerModel = standardScaler.fit(dataset)
dataset = standardScalerModel.transform(dataset)

# Define the structure of the dataset.
nb_features = len(features)
nb_classes = 2

# Define the Keras model.
model = Sequential()
model.add(Dense(600, input_shape=(nb_features,)))
model.add(Activation('relu'))
model.add(Dropout(0.2))
model.add(Dense(600))
model.add(Activation('relu'))
model.add(Dropout(0.2))
model.add(Dense(600))
model.add(Dropout(0.2))
model.add(Activation('relu'))
model.add(Dense(nb_classes))
model.add(Activation('softmax'))

# Print a summary of the model structure.
model.summary()

# Sample the dataset, else it will take too long.
dataset = dataset.sample(True, 0.01)

print(dataset.first())
# Transform the indexed label to an vector.
labelVectorTransformer = LabelVectorTransformer(output_dim=nb_classes, input_col="label_index", output_col="label")
dataset = labelVectorTransformer.transform(dataset)
print(dataset.first())
dataset = dataset.toDF()
dataset.printSchema()
dataset.cache()

# Create the distributed Ensemble trainer.
ensembleTrainer = EnsembleTrainer(model, features_col="features_normalized", merge_models=True, num_models=1)
models = ensembleTrainer.train(dataset)
# Get the model from the tuple.
model = models[0][1]
print(models)

# Apply the model prediction to the dataframe.
predictorTransformer = ModelPredictor(keras_model=model, features_col="features_normalized")
dataset = predictorTransformer.predict(dataset)
dataset.printSchema()
